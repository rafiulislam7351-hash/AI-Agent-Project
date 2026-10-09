import ast
import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from IPython.display import display, Image

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import pandas as pd
import sqlglot
from sqlglot import exp
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from langchain.tools import tool
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from models.schema import AgentSchema, JudgeSchema, ETLAgentSchema, DecideSchema, DataAgentSchema
from utils.llm_pick import pick_llm
from utils import etl_tools
from utils.etl_tools import ETLTools
from etl_analyst import etl_analyst
from sql_analyst import sql_analyst

load_dotenv()

OUTPUT_DIR = Path("outputs")
SUPPORTED_FORMATS = {"csv", "json", "parquet", "xlsx"}
FORMAT_ALIASES = {"excel": "xlsx", "xls": "xlsx", "pq": "parquet"}

ROUTER_PROMPT = """You are the main router of a data assistant. Decide which agent handles the request.

answer:
- "sql_analyst": the request is about a database, SQL, tables, rows, columns, queries,
  PostgreSQL, or listing/counting/aggregating data that lives in a database.
- "etl_analyst": the request is about files (csv, json, parquet), file paths, calling an
  API endpoint, or extracting / transforming / filtering / cleaning data files.

output_format:
- If the user says which file format they want the result in (csv, json, parquet, xlsx/excel),
  return it. Otherwise return null.
"""


#|-------------------------------------------------------Helpers------------------------------------------------------|
def _normalize_format(fmt):
    fmt = (fmt or "csv").strip().lower().lstrip(".")
    fmt = FORMAT_ALIASES.get(fmt, fmt)
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported format '{fmt}'. Choose one of {sorted(SUPPORTED_FORMATS)}")
    return fmt


def _to_dataframe(raw) -> pd.DataFrame:
    """Best-effort conversion of whatever sql_analyst returned into a DataFrame."""
    if isinstance(raw, pd.DataFrame):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        parsed = None
        for loader in (json.loads, ast.literal_eval):
            try:
                parsed = loader(text)
                break
            except Exception:
                continue
        if parsed is None:  # plain text -> one line per row
            return pd.DataFrame({"result": text.splitlines()})
        raw = parsed
    if isinstance(raw, dict):
        try:
            return pd.DataFrame(raw)
        except ValueError:
            return pd.DataFrame([raw])
    if isinstance(raw, (list, tuple)):
        return pd.DataFrame(raw) if raw else pd.DataFrame()
    return pd.DataFrame({"result": [str(raw)]})


def _read_any(path: str) -> pd.DataFrame:
    ext = Path(path).suffix.lower().lstrip(".")
    if ext == "csv":
        return pd.read_csv(path)
    if ext == "json":
        try:
            return pd.read_json(path)
        except ValueError:
            return pd.read_json(path, lines=True)
    if ext == "parquet":
        return pd.read_parquet(path)
    if ext in ("xlsx", "xls"):
        return pd.read_excel(path)
    raise ValueError(f"Cannot read file type: {path}")


def _write_any(df: pd.DataFrame, path: Path, fmt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        df.to_csv(path, index=False)
    elif fmt == "json":
        df.to_json(path, orient="records", indent=2, date_format="iso")
    elif fmt == "parquet":
        df.to_parquet(path, index=False)
    elif fmt == "xlsx":
        df.to_excel(path, index=False)


def _find_paths_in_text(text: str):
    pattern = r"[\w\-./\\:]+\.(?:csv|json|parquet|xlsx)\b"
    return [m.group(0) for m in re.finditer(pattern, text or "", flags=re.I)]


#|-------------------------------------------------------Main AI Agent-----------------------------------------------|
llm=pick_llm('high')
llm_main=llm.with_structured_output(DecideSchema)

def main_node(state: DataAgentSchema):
    """Decides which agent to use (sql_analyst / etl_analyst) and which output format the user wants."""
    user_prompt = state.messages[-1].content
    decision = llm_main.invoke([SystemMessage(content=ROUTER_PROMPT), HumanMessage(content=user_prompt)]).model_dump()

    state.main_response = decision['answer']
    # Format priority: explicit value passed in state > format found in the prompt > csv
    state.output_format = state.output_format or decision.get('output_format') or "csv"
    return state


def route_agent(state: DataAgentSchema):
    """Conditional edge: read the router's decision."""
    return "sql_node" if state.main_response == "sql_analyst" else "etl_node"


#|-------------------------------------------------------SQL Analyst Node--------------------------------------------|
def sql_node(state: DataAgentSchema):
    user_prompt = state.messages[-1].content
    result = sql_analyst.invoke({"user_question": user_prompt})

    state.final_answer = result.get("final_answer")

    if result.get("is_safe_sql_response") is False:
        state.error = f"Query blocked as unsafe: {result.get('comments')}"
        return state
    if result.get("execution_error") and "sql_query_execution_result" not in result:
        state.error = f"SQL execution failed: {result['execution_error']}"
        return state

    df = _to_dataframe(result.get("sql_query_execution_result"))
    state.result_records = df.to_dict("records")
    return state


#|-------------------------------------------------------ETL Analyst Node--------------------------------------------|
def etl_node(state: DataAgentSchema):
    user_prompt = state.messages[-1].content
    fmt = _normalize_format(state.output_format)
    name = state.output_name or "etl_output"
    target = OUTPUT_DIR / f"{name}.{fmt}"
    target.parent.mkdir(parents=True, exist_ok=True)

    # Tell the ETL agent where the final result should be saved.
    prompt = f"{user_prompt}\n\nSave the final result to this destination path: {target.as_posix()}"
    result = etl_analyst.invoke({"messages": [HumanMessage(content=prompt)]})
    answer = result["messages"][-1].content if result.get("messages") else ""
    state.final_answer = answer

    # 1) ETL agent wrote exactly where we asked
    if target.exists():
        state.result_records = _read_any(str(target)).to_dict("records")
        return state

    # 2) ETL agent wrote somewhere else -> look for a path in its reply
    for p in reversed(_find_paths_in_text(answer)):
        if os.path.exists(p):
            state.result_records = _read_any(p).to_dict("records")
            return state

    state.error = "ETL agent finished but no output file was found."
    return state


#|-------------------------------------------------------Export Node-------------------------------------------------|
def export_node(state: DataAgentSchema):
    """Writes the result in the format the user chose: csv / json / parquet / xlsx."""
    if state.error or state.result_records is None:
        return state

    fmt = _normalize_format(state.output_format)
    prefix = "sql" if state.main_response == "sql_analyst" else "etl"
    name = state.output_name or f"{prefix}_output"
    path = OUTPUT_DIR / f"{name}.{fmt}"

    _write_any(pd.DataFrame(state.result_records), path, fmt)
    state.output_file = str(path)
    return state


#|-------------------------------------------------------Build the Graph---------------------------------------------|
main_graph = StateGraph(DataAgentSchema)
main_graph.add_node("main_node", main_node)
main_graph.add_node("sql_node", sql_node)
main_graph.add_node("etl_node", etl_node)
main_graph.add_node("export_node", export_node)

main_graph.add_edge(START, "main_node")
main_graph.add_conditional_edges("main_node", route_agent, {"sql_node": "sql_node", "etl_node": "etl_node"})
main_graph.add_edge("sql_node", "export_node")
main_graph.add_edge("etl_node", "export_node")
main_graph.add_edge("export_node", END)

main_agent = main_graph.compile()


if __name__ == "__main__":
    # Optional diagram: needs internet (mermaid.ink). Never block the agent if it fails.
    try:
        png = main_agent.get_graph().draw_mermaid_png(max_retries=5, retry_delay=2.0)
        with open("main_agent_graph.png", "wb") as f:
            f.write(png)
    except Exception as e:
        print(f"Could not render graph PNG: {e}")
        # Offline fallback: prints the Mermaid text, which you can paste into https://mermaid.live
        print(main_agent.get_graph().draw_mermaid())

    print("""
    ================ DATA ASSISTANT ================
    Describe your task in one sentence. I will pick the right agent:

    DATABASE (sql_analyst)  - ask about data stored in PostgreSQL
        e.g. "List the top 5 users by user_id in DESC order from the users table"
        e.g. "Show all unpaid payments from the payment table"

    FILES / API (etl_analyst) - work with csv, json or parquet files, or an API
        e.g. "Extract data from https://api.example.com/users and save it"
        e.g. "Transform data/raw/users.csv, keep only active users, save to data/clean/users.parquet"

    Tip: for file tasks, include the full file paths and the API endpoint in your sentence.
    Note: only read queries are allowed on the database (no CREATE / INSERT / UPDATE / DELETE).
    ================================================
    """)

    prompt = input("Your request: ").strip()
    while not prompt:
        prompt = input("Request cannot be empty. Your request: ").strip()

    fmt = input("Save the result as (csv / json / parquet / xlsx) [press Enter for csv]: ").strip().lower() or None
    result = main_agent.invoke({"messages": [HumanMessage(content=prompt)], "output_format": fmt})

    line = "|" + "=" * 84 + "|"
    print(line)
    print("ROUTED TO  :", result.get("main_response"))
    print(line)
    print("ANSWER     :\n", result.get("final_answer"))
    print(line)
    if result.get("error"):
        print("ERROR      :", result["error"])
    else:
        print("OUTPUT FILE:", result.get("output_file"))
    print(line)