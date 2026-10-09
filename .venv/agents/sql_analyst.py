import os
import re
import sys
from functools import lru_cache

import sqlglot
from sqlglot import exp
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END

load_dotenv()

# Allow importing from the parent directory (models/, utils/ packages)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models.schema import AgentSchema, JudgeSchema
from utils.llm_pick import pick_llm
from utils.database import dbutil

MAX_RETRIES = 2
DEFAULT_LIMIT = 10


# |------------------------------ Helpers ------------------------------|

@lru_cache(maxsize=1)
def get_db() -> dbutil:
    """Build the DB helper once and reuse it."""
    return dbutil({
        "host": os.environ["host"],
        "port": os.environ["port"],
        "database": os.environ["database"],
        "user": os.environ["user"],
        "password": os.environ["password"],
    })


@lru_cache(maxsize=1)
def get_schema_info() -> str:
    """Schema is fetched once per process, not once per question.
    Restart the app (or call get_schema_info.cache_clear()) after schema changes."""
    return get_db().schema_details("public")


REASONING_TAGS = r"(?:thought|thinking|think|reasoning)"


def extract_text(content) -> str:
    """LLM .content can be a string OR a list of content blocks; normalize to str."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content)


def remove_reasoning(content) -> str:
    """Drop <thought>...</thought> style reasoning blocks some models emit."""
    text = extract_text(content)
    text = re.sub(rf"<({REASONING_TAGS})>.*?</\1>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def strip_code_fences(content) -> str:
    """Clean LLM output down to a bare SQL string: removes reasoning blocks,
    code fences, and the trailing semicolon."""
    text = extract_text(content)

    # Unclosed reasoning tag (e.g. output cut off): keep from the first SELECT/WITH
    if re.search(rf"<{REASONING_TAGS}>", text, re.IGNORECASE) and not re.search(
        rf"</{REASONING_TAGS}>", text, re.IGNORECASE
    ):
        m = re.search(r"\b(SELECT|WITH)\b", text, re.IGNORECASE)
        text = text[m.start():] if m else text

    text = remove_reasoning(text)

    fence = re.search(r"```(?:sql)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1)

    return text.strip().rstrip(";").strip()


def check_and_limit(sql: str):
    """Deterministic guard (no LLM involved).
    Returns (ok, sql_or_reason). Ensures: parses, single statement,
    SELECT/UNION only, no mutating nodes, and a LIMIT is present."""
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.ParseError as e:
        return False, f"SQL failed to parse: {e}"

    if len(statements) != 1 or statements[0] is None:
        return False, "Query must contain exactly one statement."

    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union)):
        return False, "Only SELECT queries are allowed."

    banned = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create,
              exp.Alter, exp.Command, exp.Merge)
    if tree.find(*banned):
        return False, "Query contains a mutating or command statement."

    if not tree.args.get("limit"):
        tree = tree.limit(DEFAULT_LIMIT)

    return True, tree.sql(dialect="postgres")


# |------------------------------ Nodes ------------------------------|

def curate_questions(state: AgentSchema) -> AgentSchema:
    """Node 1: Cleans up / rephrases the raw user question using a cheap LLM."""
    llm = pick_llm("low")
    response = llm.invoke(
        "Rewrite the following question to be clear and unambiguous. "
        "Do NOT change its meaning. Return only the rewritten question.\n\n"
        f"{state.user_question}"
    )
    return {"curated_question": remove_reasoning(response.content)}


def prompt_query(state: AgentSchema) -> AgentSchema:
    """Node 2: Builds the SQL-generation prompt (adds error feedback on retries)."""
    retry_block = ""
    if state.execution_error:
        retry_block = f"""
    ## PREVIOUS ATTEMPT FAILED

    Previous query:
    {state.generated_sql_query}

    Database error:
    {state.execution_error}

    Fix the problem and return a corrected query.
    """

    prompt = f"""
    You are an SQL Analyst Agent.

    Your task is to convert the user's natural-language question into ONE executable PostgreSQL SQL query.

    ## USER QUESTION

    {state.curated_question}

    ## DATABASE SCHEMA

    {get_schema_info()}

    The database schema contains the available tables, columns, data types, and sample data.
    {retry_block}
    ## RULES

    1. Use PostgreSQL syntax only.
    2. Use ONLY tables and columns that exist in the provided database schema.
       Never invent table names, column names, relationships, or data.
    3. Use the sample data only to understand the structure and meaning of the columns.
       Do not assume the sample data represents the complete database.
    4. Generate the simplest correct SQL query that answers the question.
    5. Use JOIN, GROUP BY, HAVING, ORDER BY, aggregates, subqueries, CTEs, or window
       functions only when necessary.
    6. If the user explicitly requests a number of rows, use that number.
    7. If the user does NOT explicitly request a number of rows, add: LIMIT {DEFAULT_LIMIT}
    8. Generate only READ-ONLY SQL. Never generate INSERT, UPDATE, DELETE, DROP,
       ALTER, TRUNCATE, CREATE, GRANT, or REVOKE.
    9. Before returning, verify that all tables and columns exist, the syntax is valid,
       and the query actually answers the question.

    ## OUTPUT

    Return ONLY the SQL query: no explanations, comments, markdown, code fences,
    multiple queries, reasoning, or natural-language text.
    """
    return {"prompt_context": prompt}


def generate_sql(state: AgentSchema) -> dict:
    """Node 3: Sends the prompt to a high-tier LLM and stores the cleaned SQL."""
    llm = pick_llm("high")
    response = llm.invoke(state.prompt_context)
    return {"generated_sql_query": strip_code_fences(response.content)}


def is_safe_state(state: AgentSchema) -> dict:
    """Node 4: Two-layer guardrail. Deterministic check first, LLM judge second."""
    ok, result = check_and_limit(state.generated_sql_query)
    if not ok:
        return {"is_safe_sql_response": "No", "comments": result}

    # Use the normalized SQL (LIMIT enforced) from here on.
    safe_sql = result

    llm_judge = pick_llm("medium").with_structured_output(JudgeSchema)
    prompt = f"""You are an expert SQL Security Auditor. Decide whether the SQL query below is
    strictly READ-ONLY (safe) or contains any modifying, destructive, or unauthorized operation (unsafe).

    SAFE ("Yes"): data retrieval only (SELECT, WITH/CTE) with no state changes.

    UNSAFE ("No"):
    - DML: INSERT, UPDATE, DELETE, MERGE, REPLACE, UPSERT
    - DDL: CREATE, ALTER, DROP, TRUNCATE, RENAME
    - DCL: GRANT, REVOKE
    - Execution: EXEC, EXECUTE, CALL, PREPARE, or functions with side effects
    - Chained statements or injection via semicolons
    - Out-of-band or file operations (INTO OUTFILE, COPY, LOAD DATA, pg_read_file, etc.)

    Query:
    {safe_sql}

    Fill in is_safe ("Yes" or "No"), risk_category
    (READ_ONLY, DML_MUTATION, DDL_MUTATION, CODE_EXECUTION, or INJECTION_RISK),
    and a short explanation."""

    verdict = llm_judge.invoke(prompt)
    return {
        "generated_sql_query": safe_sql,
        "is_safe_sql_response": verdict.is_safe,
        "comments": verdict.explanation,
    }


def cancel_sql(state: AgentSchema) -> AgentSchema:
    """Node 5a (unsafe path): Explains why the query was blocked."""
    return {
        "final_answer": (
            "SQL query generation canceled due to safety concerns. "
            f"Comments: {state.comments}"
        )
    }


def execute_sql(state: AgentSchema) -> AgentSchema:
    """Node 5b (safe path): Runs the approved query. Errors are captured, not raised."""
    try:
        result = get_db().execute_sql(state.generated_sql_query)
        return {"sql_query_execution_result": result, "execution_error": ""}
    except Exception as e:
        retries = state.retry_count + 1
        update = {"execution_error": str(e), "retry_count": retries}
        if retries > MAX_RETRIES:
            update["final_answer"] = (
                f"Sorry, I couldn't run a valid query after {MAX_RETRIES + 1} attempts. "
                f"Last error: {e}"
            )
        return update


def final_answer(state: AgentSchema) -> AgentSchema:
    """Node 6: Turns the raw SQL result rows into a human-readable answer."""
    llm = pick_llm("medium")
    prompt = f"""You are an expert SQL Analyst Agent.
    Give the user a clear, concise, human-readable answer based on the executed SQL result,
    summarizing the key findings.

    ### User Question:
    {state.curated_question}

    ### SQL Query Execution Result:
    {state.sql_query_execution_result}
    """
    return {"final_answer": remove_reasoning(llm.invoke(prompt).content)}


# |------------------------------ Routers ------------------------------|

def route_after_safety(state: AgentSchema) -> str:
    return "execute_sql" if state.is_safe_sql_response.strip().lower() == "yes" else "cancel_sql"


def route_after_execution(state: AgentSchema) -> str:
    if not state.execution_error:
        return "final_answer"
    if state.retry_count <= MAX_RETRIES:
        return "prompt_query"  # repair loop: regenerate with the error as feedback
    return END  # retries exhausted; execute_sql already set final_answer


# |------------------------------ Graph ------------------------------|

sql_graph = StateGraph(AgentSchema)

sql_graph.add_node("curate_questions", curate_questions)
sql_graph.add_node("prompt_query", prompt_query)
sql_graph.add_node("generate_sql", generate_sql)
sql_graph.add_node("is_safe_state", is_safe_state)
sql_graph.add_node("cancel_sql", cancel_sql)
sql_graph.add_node("execute_sql", execute_sql)
sql_graph.add_node("final_answer", final_answer)

sql_graph.add_edge(START, "curate_questions")
sql_graph.add_edge("curate_questions", "prompt_query")
sql_graph.add_edge("prompt_query", "generate_sql")
sql_graph.add_edge("generate_sql", "is_safe_state")

sql_graph.add_conditional_edges(
    "is_safe_state",
    route_after_safety,
    {"execute_sql": "execute_sql", "cancel_sql": "cancel_sql"},
)
sql_graph.add_conditional_edges(
    "execute_sql",
    route_after_execution,
    {"final_answer": "final_answer", "prompt_query": "prompt_query", END: END},
)

sql_graph.add_edge("cancel_sql", END)
sql_graph.add_edge("final_answer", END)

sql_analyst = sql_graph.compile()


if __name__ == "__main__":
    # Optional: render the graph diagram (needs internet for mermaid.ink)
    try:
        with open("sql_analyst_graph.png", "wb") as f:
            f.write(sql_analyst.get_graph().draw_mermaid_png())
    except Exception as e:
        print(f"Could not render graph PNG: {e}")

    # Only user_question is required; every other field has a default in AgentSchema.
    result = sql_analyst.invoke({
        "user_question": "List the top 5 users according to user_id in DESC order from the users table"
    })

    line = "|" + "=" * 84 + "|"
    print(line)
    # .get() because the graph only returns fields that some node actually wrote
    # (e.g. no execution result exists when the query was blocked).
    print("CURATED QUESTION:\n", result.get("curated_question"))
    print(line)
    print("GENERATED SQL:\n", result.get("generated_sql_query"))
    print(line)
    print("SAFE?:", result.get("is_safe_sql_response"), "|", result.get("comments"))
    print(line)
    print("EXECUTION RESULT:\n", result.get("sql_query_execution_result", "(query was not executed)"))
    print(line)
    print("RETRIES:", result.get("retry_count", 0), "| LAST ERROR:", result.get("execution_error") or "none")
    print(line)
    print("FINAL ANSWER:\n", result.get("final_answer"))
    print(line)