import os
import sys
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from dotenv import load_dotenv
load_dotenv()

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models.schema import AgentSchema , JudgeSchema
from utils.llm_pick import pick_llm


#----------------------------------------------------------------------------------
# Initialize LLM with structured output binding
llm = pick_llm("high")
llm_judge = llm.with_structured_output(JudgeSchema)

sql_query = "SELECT * FROM users WHERE age > 30;"

prompt=f"""You are an expert SQL Security Auditor and Judge. Your sole task is to evaluate the provided SQL query and determine whether it is strictly READ-ONLY (safe) or contains any modifying, destructive, or unauthorized security-risk operations (unsafe).

### Evaluation Criteria:
1. SAFE ('Yes'):
   - Queries strictly limited to data retrieval (e.g., SELECT, WITH/CTE statements, SHOW, DESCRIBE).
   - Read-only operations that do not mutate database schema, data, or environment state.

2. UNSAFE ('No'):
   - Data Manipulation Language (DML) mutations: INSERT, UPDATE, DELETE, MERGE, REPLACE, UPSERT.
   - Data Definition Language (DDL) changes: CREATE, ALTER, DROP, TRUNCATE, RENAME.
   - Data Control / Grant operations: GRANT, REVOKE.
   - Executable/Control commands: EXEC, EXECUTE, CALL, SP_*, PREPARE.
   - Multi-statement execution or injection techniques using semicolons (`;`) attempting to chain commands.
   - System/Administrative functions that can alter state or leak out-of-band data (e.g., INTO OUTFILE, LOAD DATA, XP_CMDSHELL).
   
### Input Query:
{sql_query}

### Output:
[
  "is_safe": "Yes" | "No",
  "risk_category": "READ_ONLY" | "DML_MUTATION" | "DDL_MUTATION" | "CODE_EXECUTION" | "INJECTION_RISK",
  "explanation": "<Clear, concise rationale explaining why the query was marked safe or unsafe. Mention specific keywords or risk factors found.>"
]"""

print(llm_judge.invoke(prompt))