 Agentic AI Data Assistant
A multi-agent data assistant built with LangGraph that understands natural-language requests and routes them to the right workflow:
SQL Analyst Agent — generates, validates, and executes read-only SQL queries against PostgreSQL.
ETL Analyst Agent — works with files and APIs to extract, transform, and export data.
Main Agent — classifies the request and routes it to the appropriate sub-agent.
Export workflow — helps return or save results in formats such as CSV, JSON, and Parquet, depending on the task.
The project explores how agentic workflows can connect LLM reasoning, database querying, and data processing in one system.
LLM provider: This project uses the free API option available through Google AI Studio / Gemini. Availability, quotas, and model access are controlled by Google and may change.
 Features
 Main Agent
Accepts a request written in natural language.
Routes database questions to the SQL workflow and file/API tasks to the ETL workflow.
Sends the processed result to the export stage.
 SQL Analyst Agent
Turns natural-language questions into PostgreSQL queries.
Uses database schema/context to help generate relevant SQL.
Checks SQL safety before execution.
Is intended for read-only database queries; write or destructive operations should be rejected.
Returns query results in a user-friendly form.
Example request:
List the top 5 users by user_id in DESC order from the users table
​
Example result:
Column: user_id
Rows: 10000, 9999, 9998, 9997, 9996
​
 ETL Analyst Agent
Supports data extraction and transformation workflows.
Can work with API responses and structured files such as CSV, JSON, and Parquet, depending on the implemented tools.
Uses tools to process data and save outputs to a requested location.
Example requests:
Extract data from <https://api.example.com/users> and save it to data/extract/users.csv
​
Transform data/raw/users.csv, keep only active users, and save it to data/clean/users.parquet
​
For file operations, provide the full file path when possible. For API extraction, include the complete API endpoint.
 Safety-oriented SQL workflow
The SQL workflow is designed to check a generated query before running it. Database requests should be limited to read-only operations such as SELECT. Safety checks are useful safeguards, but they are not a substitute for database permissions: use a PostgreSQL account that has only the minimum required read privileges.
 Architecture
The system uses a main router and specialized sub-agents.
flowchart TD
    A([Start]) --> B[Main Agent: main_node]
    B -.-> C[ETL Agent: etl_node]
    B -.-> D[SQL Agent: sql_node]
    C --> E[Export: export_node]
    D --> E
    E --> F([End])

    subgraph SQL_Agent[SQL Analyst Sub-Agent]
      S1[curate_questions] --> S2[prompt_query]
      S2 --> S3[generate_sql]
      S3 --> S4{is_safe_state}
      S4 -. Unsafe .-> S5[cancel_sql]
      S4 -. Safe .-> S6[execute_sql]
      S6 -. Needs refinement .-> S2
      S6 --> S7[final_answer]
    end

    subgraph ETL_Agent[ETL Analyst Sub-Agent]
      T1([Start]) --> T2[llm_node]
      T2 -. Tool call .-> T3[tool_node]
      T3 --> T2
      T2 -. Done .-> T4([End])
    end
ETL Analyst Sub-Agent

SQL Analyst Sub-Agent

Start

llm_node

tool_node

End

curate_questions

prompt_query

generate_sql

is_safe_state

cancel_sql

execute_sql

final_answer

Start

Main Agent: main_node

ETL Agent: etl_node

SQL Agent: sql_node

Export: export_node

End

Unsafe

Safe

Needs refinement

Tool call

Done

​
High-level flow
The user submits a request.
The main agent identifies whether the task is database-related or ETL-related.
The appropriate sub-agent processes the request.
The SQL agent curates the question, generates SQL, checks its safety, and executes an approved query.
The ETL agent uses its available tools for API/file extraction or transformation.
The export workflow returns or saves the result.
 Tech Stack
Python — application logic
LangGraph — agent workflow orchestration
LLM via Google Gemini API — language understanding and generation
PostgreSQL — database querying for SQL tasks
Pandas — data transformation where implemented
python-dotenv — environment variable configuration
uv — Python project and dependency management
The exact dependencies are defined by the project's pyproject.toml and uv.lock files.
 Prerequisites
Before running the project, install:
Python version required by pyproject.toml (Python 3.12+ is recommended if that matches your project configuration).
Git, if cloning the repository.
uv.
A Google AI Studio API key for Gemini.
PostgreSQL and access to a database, if you want to use the SQL workflow.
 Installation
1. Clone the repository
Replace the placeholder URL with your repository URL:
git clone <YOUR_REPOSITORY_URL>
cd <YOUR_PROJECT_FOLDER>
​
If you already have the project files, open a terminal in the project root directory instead.
2. Install uv
Run:
pip install uv
​
If your terminal cannot find uv after installation, restart the terminal and check the official uv installation guide.
3. Install project dependencies
From the directory containing pyproject.toml, run:
uv sync
​
uv sync creates or updates the project's virtual environment and installs the dependencies declared in the project configuration and lockfile.
4. Configure your .env file
Create a file named .env in the project root (the same directory as pyproject.toml). Add the environment variables expected by your code.
For example:
# Google AI Studio / Gemini
GOOGLE_API_KEY=your_google_ai_studio_api_key

# PostgreSQL — update these values for your own database
PGHOST=localhost
PGPORT=5432
PGUSER=your_postgres_user
PGPASSWORD=your_postgres_password
PGDATABASE=your_database_name
​
Important: These variable names are examples. Your application must use the same names that your code reads. If your code expects names such as GEMINI_API_KEY or host, update this template to match the implementation.
Get a Gemini API key
Open Google AI Studio.
Sign in and create an API key.
Put the key in your local .env file.
Check Google's current terms, model availability, and usage limits.
Never commit your real .env file or API key to GitHub. Add .env to .gitignore. If a key is accidentally exposed, revoke it and create a new one.
Example .gitignore entries:
.env
.venv/
__pycache__/
*.py[cod]
​
5. Prepare PostgreSQL (SQL workflow only)
Make sure PostgreSQL is running and reachable.
Update the database values in .env.
Ensure the target database contains the tables you want to query.
Prefer a database user with read-only permissions for this assistant.
If your repository includes a database setup or data-loading script, review it before running it and follow the instructions in that script. Do not run setup scripts against a production database unless you understand their effects.
6. Run the application
Check the project's entry point and use the command that matches your code. For example, if main.py starts the CLI:
uv run python main.py
​
If the application uses another entry point, run that entry point instead. Follow any prompts displayed by the application.
 Example Requests
Database query
List the top 5 users by user_id in DESC order from the users table
​
Expected behavior: the SQL agent generates a read-only query, validates it, executes it, and returns the five highest user_id values.
API extraction
Extract data from <https://api.example.com/users> and save it to data/extract/users.csv
​
Replace the example endpoint with a real API endpoint that you are authorized to access.
File transformation
Transform data/raw/users.csv, keep only active users, and save it to data/clean/users.parquet
​
Make sure the input file exists and that the destination directory is writable.
 Project Structure
The following is an illustrative structure based on the agent architecture. Adjust it to match the actual files in your repository.
your-project/
├── agents/
│   ├── data_agent.py          # Main router agent
│   ├── sql_analyst.py         # SQL workflow
│   └── etl_analyst.py         # ETL workflow
├── Models/
│   └── schema.py              # State / structured-output models
├── utils/
│   ├── database.py            # PostgreSQL helpers
│   ├── etl_tools.py           # ETL tools
│   └── llm_pick.py            # LLM configuration, if used
├── data/
│   ├── raw/
│   ├── extract/
│   └── clean/
├── .env                       # Local secrets; do not commit
├── .gitignore
├── main.py                    # Application entry point, if applicable
├── pyproject.toml
├── uv.lock
└── README.md
​
 Security Notes
Keep API keys and database passwords in .env, never in source code.
Never commit .env to a public repository.
Use a dedicated PostgreSQL user with only the permissions the agent needs.
Keep SQL safety validation enabled.
Treat LLM-generated SQL and code as untrusted until validated.
Use only APIs and files you are authorized to access.
Review generated output paths before writing files.
Free API access can have quotas, rate limits, and changing availability; “free” does not mean unlimited.
 Troubleshooting
uv is not recognized
Restart your terminal. If the problem remains, follow the official uv installation guide.
API key missing or authentication fails
Check that .env exists in the project root, that the key is correct, and that the variable name matches what your code reads.
PostgreSQL connection fails
Check that PostgreSQL is running and verify the host, port, username, password, database name, and network access.
Module not found
Run uv sync from the directory containing pyproject.toml, then launch the application with uv run ....
An ETL request cannot find a file
Check the file path, spelling, working directory, and whether the application has permission to read the file.
 Contributing
Suggestions, bug reports, and improvements are welcome. Before submitting a change:
Explain the issue or feature.
Keep changes consistent with the existing architecture.
Test the affected workflow.
Do not include secrets, API keys, or private data in commits.
 Resources
Google AI Studio
Gemini API documentation
LangGraph documentation
uv documentation
PostgreSQL documentation
Pandas documentation
 About
This project is a hands-on exploration of agentic AI, SQL automation, ETL workflows, and data engineering. It is built as a learning project and will evolve as the architecture and capabilities improve.
If you find the project useful, consider giving the repository a  and sharing suggestions or feedback.
Note: Update this README's project structure, environment variable names, and run command to match your actual implementation before publishing the repository.
