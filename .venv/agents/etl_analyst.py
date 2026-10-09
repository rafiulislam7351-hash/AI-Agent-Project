import os
import re
import sys
from functools import lru_cache
from IPython.display import display, Image

from utils import etl_tools
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import sqlglot
from sqlglot import exp
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from langchain.tools import tool
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from models.schema import AgentSchema, JudgeSchema, ETLAgentSchema
from utils.llm_pick import pick_llm
from utils.etl_tools import ETLTools


load_dotenv()

#-------------------------------------------------------AI AGent-----------------------------------------------|

@tool
def extract_load_tool(url: str, output_folder: str, format: str) -> str:
    """Extracts data from an API URL and saves it to output_folder in the given format."""
    return ETLTools().extract_load(url, output_folder, format)


@tool
def transform_load_tool(input_file_path: str, output_folder: str,
                        output_format: str, user_question: str) -> str:
    """Transforms data from input_file_path per user_question and saves it to output_folder."""
    etl_tool = ETLTools()
    top_3_rows = etl_tool.transform_load_context(input_file_path, output_folder, output_format)

    prompt = f"""You are a Python Data Analyst who uses Pandas. Provide ONLY Pandas code,
    no explanation or comments. Load the data from: {input_file_path}
    then transform it and save it to: {output_folder} as {output_format}.
    User's question: {user_question}
    Sample of the data: {top_3_rows}"""

    response = pick_llm('high').invoke(prompt).content
    code = re.sub(r"^```(?:python)?\s*|\s*```$", "", response.strip())
    results = etl_tool.execute_code(code)
    return (f"Data transformed and saved at {output_folder} in {output_format}.\n\n"
            f"Code executed:\n{code}\n\nResult:\n{results}")


tools=[extract_load_tool,transform_load_tool]

tools_by_name = {t.name: t for t in tools}
llm_bind = pick_llm('high').bind_tools(tools)

SYSTEM_PROMPT = """You are a Python Data Analyst with tools to extract/load and transform/load data.
Perform the right ETL operation for the user's question. Once done, inform the user and stop."""

def llm_node(state: ETLAgentSchema):
    response = llm_bind.invoke([SystemMessage(content=SYSTEM_PROMPT)] + state.messages)
    return {"messages": [response]}

def tool_node(state: ETLAgentSchema):
    results = []
    for call in state.messages[-1].tool_calls:
        obs = tools_by_name[call["name"]].invoke(call["args"])
        results.append(ToolMessage(content=str(obs), tool_call_id=call["id"]))
    return {"messages": results}
    
    
#|------------------------------------Agent Node & Edges-------------------------------------------|
# Nodes------------|
etl_analyst_graph=StateGraph(ETLAgentSchema)
etl_analyst_graph.add_node("llm_node", llm_node)
etl_analyst_graph.add_node("tool_node", tool_node)

# Edges------------|
etl_analyst_graph.add_edge(START,"llm_node")
def is_tool_call(state:ETLAgentSchema):
    tool_calls=state.messages[-1].tool_calls
    
    if tool_calls:
        return "tool_node"
    else:
        return "end"

etl_analyst_graph.add_conditional_edges('llm_node',is_tool_call,
                                        {
                                            "tool_node":"tool_node",
                                            "end":END
                                        }
                                        )

etl_analyst_graph.add_edge("tool_node","llm_node")
etl_analyst=etl_analyst_graph.compile()

if __name__=='__main__':
    
    img=Image(etl_analyst.get_graph().draw_mermaid_png())
    with open("etl_analyst_graph.png","wb") as f:
        f.write(img.data)
     
    #|----------------Extracting data From API Endpoint----------------------------------|
    prompt_extract=input("Give Us the prompt Including API Endpoint: ")   
    extract_etl=etl_analyst.invoke({"messages":[HumanMessage(content=prompt_extract)]})
    print(extract_etl)
    
    #|----------------------Transforming The Extracted Data-------------------------------|
    
    
    prompt_transform=input("Give Us the prompt Including path for extracted_data, Path for destination and Path for filter: ")   
    extract_etl=etl_analyst.invoke({"messages":[HumanMessage(content=prompt_transform)]})
    print(extract_etl)