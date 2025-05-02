import streamlit as st
import snowflake.connector
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta

# Initialize session state
if 'conn' not in st.session_state:
    st.session_state.conn = None
if 'current_db' not in st.session_state:
    st.session_state.current_db = None

# Enhanced Theme-aware CSS with better text visibility
def apply_theme():
    # Inject CSS compatible with both dark and light themes
    st.markdown("""
        <style>
            .metric-card, .info-box {
                padding: 1rem;
                border-radius: 10px;
                margin-bottom: 1rem;
            }

            /* Adjust colors based on Streamlit theme */
            [data-testid="stAppViewContainer"] .metric-card {
                background-color: var(--secondary-background-color);
                color: var(--text-color);
                border: 1px solid var(--primary-color);
            }

            [data-testid="stAppViewContainer"] .info-box {
                background-color: var(--background-color);
                color: var(--text-color);
                border: 1px solid var(--primary-color);
            }

            h2, h3, h4, p, ul, li {
                color: var(--text-color);
            }

            /* Improve spacing on mobile */
            @media screen and (max-width: 768px) {
                .metric-card, .info-box {
                    padding: 0.5rem;
                }
            }
        </style>
    """, unsafe_allow_html=True)


# Connection functions
def connect_to_snowflake(account, username, password, warehouse, role):
    try:
        conn = snowflake.connector.connect(
            user=username,
            password=password,
            account=account,
            warehouse=warehouse,
            role=role
        )
        st.session_state.conn = conn
        st.success("✅ Successfully connected to Snowflake!")
        return True
    except Exception as e:
        st.error(f"❌ Connection failed: {str(e)}")
        return False

def disconnect_from_snowflake():
    if st.session_state.conn:
        st.session_state.conn.close()
        st.session_state.conn = None
        st.session_state.current_db = None
    st.success("🔒 Disconnected from Snowflake")

def execute_query(query):
    if st.session_state.conn:
        try:
            cursor = st.session_state.conn.cursor()
            cursor.execute(query)
            return cursor.fetchall()
        except Exception as e:
            st.error(f"Query failed: {str(e)}")
            return None
    return None

def set_current_database(db):
    """Set the current database context"""
    try:
        execute_query(f"USE DATABASE {db}")
        st.session_state.current_db = db
        return True
    except Exception as e:
        st.error(f"Couldn't set database: {str(e)}")
        return False

# Account Information Functions (fully compatible)
def get_account_info():
    """Get account type and credit information with edition-compatible queries"""
    try:
        # Get account edition (works in all editions)
        account_info = execute_query("SELECT CURRENT_ACCOUNT()")
        if account_info:
            account_name = account_info[0][0]
            edition = "Enterprise" if "enterprise" in account_name.lower() else "Standard" if "standard" in account_name.lower() else "Trial"
        else:
            edition = "Unknown"
        
        # Get approximate credit usage (alternative approach)
        credit_usage = execute_query("""
        SELECT SUM(CREDITS_USED) 
        FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY 
        WHERE START_TIME >= DATEADD(month, -1, CURRENT_DATE())
        """)
        credit_balance = credit_usage[0][0] if credit_usage and credit_usage[0][0] is not None else "N/A"
        
        return {
            'account_type': edition,
            'credit_balance': credit_balance
        }
    except Exception as e:
        st.error(f"Error getting account info: {str(e)}")
        return {'account_type': 'Unknown', 'credit_balance': 'N/A'}

def get_warehouse_usage():
    """Get warehouse credit usage with correct column names"""
    query = """
    SELECT 
        WAREHOUSE_NAME,
        SUM(CREDITS_USED) AS TOTAL_CREDITS,
        AVG(CREDITS_USED) AS AVG_CREDITS_PER_DAY,
        COUNT(*) AS QUERY_COUNT
    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
    WHERE START_TIME >= DATEADD(day, -30, CURRENT_DATE())
    GROUP BY WAREHOUSE_NAME
    ORDER BY TOTAL_CREDITS DESC
    """
    return execute_query(query)

def get_top_queries():
    """Get top queries by credit consumption with correct column names"""
    query = """
    SELECT 
        QUERY_ID,
        QUERY_TEXT,
        USER_NAME,
        WAREHOUSE_NAME,
        TOTAL_ELAPSED_TIME/1000 AS EXECUTION_TIME_SEC,
        ROUND((EXECUTION_TIME_SEC * WAREHOUSE_SIZE_COEFFICIENT)/3600, 4) AS CREDITS_USED,
        START_TIME
    FROM (
        SELECT 
            QUERY_ID,
            QUERY_TEXT,
            USER_NAME,
            WAREHOUSE_NAME,
            TOTAL_ELAPSED_TIME,
            START_TIME,
            CASE 
                WHEN WAREHOUSE_SIZE = 'X-Small' THEN 1
                WHEN WAREHOUSE_SIZE = 'Small' THEN 2
                WHEN WAREHOUSE_SIZE = 'Medium' THEN 4
                WHEN WAREHOUSE_SIZE = 'Large' THEN 8
                WHEN WAREHOUSE_SIZE = 'X-Large' THEN 16
                WHEN WAREHOUSE_SIZE = '2X-Large' THEN 32
                WHEN WAREHOUSE_SIZE = '3X-Large' THEN 64
                WHEN WAREHOUSE_SIZE = '4X-Large' THEN 128
                ELSE 1 
            END AS WAREHOUSE_SIZE_COEFFICIENT
        FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
        WHERE START_TIME >= DATEADD(day, -7, CURRENT_DATE())
        AND WAREHOUSE_NAME IS NOT NULL
    )
    ORDER BY CREDITS_USED DESC
    LIMIT 50
    """
    return execute_query(query)

def get_table_stage_files(db, schema, table):
    """Safely list files in a table stage"""
    try:
        # First set the database context
        if not set_current_database(db):
            return None
        
        # Then list the files
        query = f"LIST @%{table}"
        return execute_query(query)
    except Exception as e:
        st.error(f"Error accessing table stage: {str(e)}")
        return None

def get_internal_stage_files(db, schema, stage):
    """Safely list files in an internal stage"""
    try:
        # First set the database context
        if not set_current_database(db):
            return None
        
        # Then list the files
        query = f"LIST @{stage}"
        return execute_query(query)
    except Exception as e:
        st.error(f"Error accessing internal stage: {str(e)}")
        return None

def get_all_stages():
    """Get all stages across all databases with safe queries"""
    databases = get_all_databases()
    all_stages = []
    
    for db in databases:
        if set_current_database(db):
            schemas = get_all_schemas(db)
            for schema in schemas:
                stages = execute_query(f"SHOW STAGES IN SCHEMA {schema}")
                if stages:
                    for stage in stages:
                        stage_name = stage[0]
                        stage_type = stage[5]
                        stage_path = f"{db}.{schema}.{stage_name}" if stage_type == "INTERNAL" else stage_name
                        
                        all_stages.append({
                            'Database': db,
                            'Schema': schema,
                            'Stage Name': stage_name,
                            'Type': stage_type,
                            'Path': stage_path
                        })
    
    return all_stages

def get_all_databases():
    """Get all accessible databases"""
    query = "SHOW DATABASES"
    results = execute_query(query)
    return [db[1] for db in results] if results else []

def get_all_schemas(db):
    """Get schemas within a database"""
    if not set_current_database(db):
        return []
    query = "SHOW SCHEMAS"
    results = execute_query(query)
    return [schema[1] for schema in results] if results else []

def get_user_stage_files():
    """Get files in user stage with proper query"""
    try:
        return execute_query("LIST @~")
    except Exception as e:
        st.error(f"Error accessing user stage: {str(e)}")
        return None

# UI Components with proper error handling
def display_account_overview():
    st.header("📊 Account Overview")
    
    account_info = get_account_info()
    if not account_info:
        st.warning("Could not retrieve account information")
        return
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown(f"""
        <div class="metric-card">
            <h3>Account Type</h3>
            <h2>{account_info.get('account_type', 'Unknown')}</h2>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div class="metric-card">
            <h3>Approx. Monthly Credits</h3>
            <h2>{account_info.get('credit_balance', 'N/A')}</h2>
        </div>
        """, unsafe_allow_html=True)

def display_warehouse_usage():
    st.header("🏭 Warehouse Credit Usage")
    
    warehouse_data = get_warehouse_usage()
    if not warehouse_data:
        st.warning("No warehouse usage data available")
        return
    
    df = pd.DataFrame(warehouse_data, columns=[
        "Warehouse", "Total Credits", "Avg Credits/Day", "Query Count"
    ])
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.dataframe(df.sort_values("Total Credits", ascending=False))
    
    with col2:
        fig = px.pie(df, values='Total Credits', names='Warehouse', 
                     title='Credit Usage by Warehouse',
                     color_discrete_sequence=px.colors.qualitative.Pastel)
        st.plotly_chart(fig, use_container_width=True)

def display_top_queries():
    tab1, tab2 = st.tabs(["🔍 Top Queries by Credit Usage", "💾 Storage Optimization (MB)"])
    
    with tab1:
        queries = get_top_queries()
        if not queries:
            st.warning("No query history available")
            return
        
        df = pd.DataFrame(queries, columns=[
            "Query ID", "Query Text", "User", "Warehouse", 
            "Execution Time (sec)", "Credits Used", "Start Time"
        ])
        
        st.dataframe(df)
        
        selected_query = st.selectbox("Select a query to view details", df["Query ID"])
        query_details = df[df["Query ID"] == selected_query].iloc[0]
        
        st.markdown(f"""
        <div class="info-box">
            <h4>Query Details: {selected_query}</h4>
            <p><strong>User:</strong> {query_details['User']}</p>
            <p><strong>Warehouse:</strong> {query_details['Warehouse']}</p>
            <p><strong>Execution Time:</strong> {query_details['Execution Time (sec)']:.2f} seconds</p>
            <p><strong>Credits Used:</strong> {query_details['Credits Used']:.4f}</p>
            <p><strong>Start Time:</strong> {query_details['Start Time']}</p>
        </div>
        """, unsafe_allow_html=True)
    
    with tab2:
        try:
            # Daily database storage in MB
            daily_db_query = """
            SELECT 
                DATE_TRUNC('DAY', TABLE_CREATED) as USAGE_DATE,
                SUM(ACTIVE_BYTES + TIME_TRAVEL_BYTES + FAILSAFE_BYTES) / (1024*1024) as DATABASE_MB
            FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS
            WHERE TABLE_CREATED >= DATEADD(month, -1, CURRENT_DATE())
            GROUP BY USAGE_DATE
            ORDER BY USAGE_DATE
            """
            daily_db_df = pd.read_sql(daily_db_query, st.session_state.conn)
            
            # Convert to datetime if needed
            daily_db_df['USAGE_DATE'] = pd.to_datetime(daily_db_df['USAGE_DATE'])

            # Current database storage in MB
            current_db_query = """
            SELECT 
                SUM(ACTIVE_BYTES + TIME_TRAVEL_BYTES + FAILSAFE_BYTES) / (1024*1024) as STORAGE_MB
            FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS
            WHERE TABLE_DROPPED IS NULL
            """
            current_db_df = pd.read_sql(current_db_query, st.session_state.conn)
            
            # Stage storage in MB - with proper aggregation
            stage_storage_query = """
            SELECT 
                DATE_TRUNC('DAY', USAGE_DATE) as USAGE_DATE,
                SUM(AVERAGE_STAGE_BYTES) / COUNT(*) / (1024*1024) as STAGE_MB
            FROM SNOWFLAKE.ACCOUNT_USAGE.STAGE_STORAGE_USAGE_HISTORY
            WHERE USAGE_DATE >= DATEADD(month, -1, CURRENT_DATE())
            GROUP BY USAGE_DATE
            ORDER BY USAGE_DATE
            """
            stage_storage_df = pd.read_sql(stage_storage_query, st.session_state.conn)
            
            # Convert to datetime if needed
            if not stage_storage_df.empty:
                stage_storage_df['USAGE_DATE'] = pd.to_datetime(stage_storage_df['USAGE_DATE'])

            # Display current metrics
            col1, col2 = st.columns(2)
            
            with col1:
                if not current_db_df.empty and not pd.isna(current_db_df['STORAGE_MB'].iloc[0]):
                    db_storage = current_db_df['STORAGE_MB'].iloc[0]
                    st.metric("Current Database Storage (MB)", round(db_storage, 2))
                else:
                    st.metric("Current Database Storage (MB)", "N/A")
            
            with col2:
                if not stage_storage_df.empty:
                    latest_stage = stage_storage_df.iloc[-1]['STAGE_MB']
                    st.metric("Latest Stage Storage (MB)", round(latest_stage, 2))
                else:
                    st.metric("Latest Stage Storage (MB)", "N/A")
            
            # Create combined bar chart for daily usage
            if not daily_db_df.empty and not stage_storage_df.empty:
                # Ensure consistent date formatting
                daily_db_df['USAGE_DATE'] = daily_db_df['USAGE_DATE'].dt.date
                stage_storage_df['USAGE_DATE'] = stage_storage_df['USAGE_DATE'].dt.date
                
                # Create plotly express figure instead of using go.Figure()
                fig = px.bar(
                    pd.concat([
                        daily_db_df.assign(STORAGE_TYPE='Database Storage'),
                        stage_storage_df.assign(STORAGE_TYPE='Stage Storage')
                    ]),
                    x='USAGE_DATE',
                    y='DATABASE_MB' if 'DATABASE_MB' in daily_db_df else 'STAGE_MB',
                    color='STORAGE_TYPE',
                    barmode='group',
                    title='Daily Storage Usage (MB)',
                    labels={
                        'USAGE_DATE': 'Date',
                        'DATABASE_MB': 'Storage Used (MB)',
                        'STAGE_MB': 'Storage Used (MB)'
                    }
                )
                
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("Insufficient data to display daily usage chart")
                    
        except Exception as e:
            st.error(f"Error fetching storage data: {str(e)}")																			

def display_stage_explorer():
    st.header("📂 Stage Explorer")
    
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "All Stages", 
        "Table Stages", 
        "Internal Stages", 
        "External Stages",
        "User Stage"
    ])
    
    with tab1:
        st.subheader("All Stages in Account")
        with st.spinner("Loading all stages (this may take a moment)..."):
            stages = get_all_stages()
        
        if stages:
            df = pd.DataFrame(stages)
            st.dataframe(df)
        else:
            st.warning("No stages found in account")
    
    with tab2:
        st.subheader("Table Stages")
        databases = get_all_databases()
        if databases:
            db = st.selectbox("Select Database", databases, key="table_stage_db")
            if set_current_database(db):
                schemas = get_all_schemas(db)
                if schemas:
                    schema = st.selectbox("Select Schema", schemas, key="table_stage_schema")
                    tables = execute_query(f"SHOW TABLES IN SCHEMA {schema}")
                    if tables:
                        table_names = [t[1] for t in tables]
                        table = st.selectbox("Select Table", table_names, key="table_stage_select")
                        
                        if st.button("List Table Stage Files"):
                            with st.spinner(f"Loading files from table stage..."):
                                files = get_table_stage_files(db, schema, table)
                                if files:
                                    df = pd.DataFrame(files, columns=[
                                        "File Path", "Size (bytes)", "MD5", "Last Modified"
                                    ])
                                    st.dataframe(df)
                                else:
                                    st.info("No files found in table stage")
    
    with tab3:
     st.subheader("Internal Stages")
     databases = get_all_databases()
     if databases:
        db = st.selectbox("Select Database", databases, key="int_stage_db")
        if set_current_database(db):
            schemas = get_all_schemas(db)
            if schemas:
                schema = st.selectbox("Select Schema", schemas, key="int_stage_schema")
                
                # Query stages from information_schema instead of SHOW STAGES
                stages_query = f"""
                    SELECT stage_name, stage_type 
                    FROM {db}.information_schema.stages 
                """
                stages = execute_query(stages_query)
                
                if stages:
                    # Filter for internal stages (stage_type = 'INTERNAL')
                    int_stages = [s[0] for s in stages if s[1] == "Internal Named"]
                    if int_stages:
                        stage = st.selectbox("Select Stage", int_stages, key="int_stage_select")
                        
                        if st.button("List Internal Stage Files"):
                            with st.spinner(f"Loading files from internal stage..."):
                                files = get_internal_stage_files(db, schema, stage)
                                if files:
                                    df = pd.DataFrame(files, columns=[
                                        "File Path", "Size (bytes)", "MD5", "Last Modified"
                                    ])
                                    st.dataframe(df)
                                else:
                                    st.info("No files found in internal stage")
                    else:
                        st.warning("No internal stages found in this schema")
                else:
                    st.warning("No stages found in this schema")
    with tab4:
     st.subheader("External Stages")
     databases = get_all_databases()
     if databases:
        db = st.selectbox("Select Database", databases, key="int_external_stage_db")
        if set_current_database(db):
            schemas = get_all_schemas(db)
            if schemas:
                schema = st.selectbox("Select Schema", schemas, key="int_external_stage_schema")
                
                # Query stages from information_schema instead of SHOW STAGES
                stages_query = f"""
                    SELECT stage_name, stage_type 
                    FROM {db}.information_schema.stages 
                """
                stages = execute_query(stages_query)
                
                if stages:
                    # Filter for internal stages (stage_type = 'INTERNAL')
                    int_stages = [s[0] for s in stages if s[1] == "External Named"]
                    if int_stages:
                        stage = st.selectbox("Select Stage", int_stages, key="int_external_stage_select")
                        
                        if st.button("List External Stage Files"):
                            with st.spinner(f"Loading files from external stage..."):
                                files = get_internal_stage_files(db, schema, stage)
                                if files:
                                    df = pd.DataFrame(files, columns=[
                                        "File Path", "Size (bytes)", "MD5", "Last Modified"
                                    ])
                                    st.dataframe(df)
                                else:
                                    st.info("No files found in external stage")
                    else:
                        st.warning("No external stages found in this schema")
                else:
                    st.warning("No stages found in this schema")
                    
                       
    with tab5:
        st.subheader("User Stage (@~)")
        if st.button("List My User Stage Files"):
            with st.spinner("Loading user stage files..."):
                files = get_user_stage_files()
                if files:
                    df = pd.DataFrame(files, columns=[
                        "File Path", "Size (bytes)", "MD5", "Last Modified"
                    ])
                    st.dataframe(df)
                else:
                    st.info("No files found in user stage")

# Main App
def main():
    st.set_page_config(layout="wide", page_title="Snowflake Account Dashboard")
    apply_theme()
    
    st.title("❄️ Snowflake Account Usage Dashboard")
    
    # Sidebar Connection
    with st.sidebar:
        st.header("🔑 Snowflake Connection")
        account = st.text_input("Account", placeholder="your-account.snowflakecomputing.com")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        warehouse = st.text_input("Warehouse", placeholder="COMPUTE_WH")
        role = st.text_input("Role", placeholder="SYSADMIN")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Connect", type="primary"):
                connect_to_snowflake(account, username, password, warehouse, role)
        with col2:
            if st.button("Disconnect"):
                disconnect_from_snowflake()
        
        st.markdown("---")
        st.markdown("""
        <div class="info-box">
            <h4>ℹ️ Dashboard Information</h4>
            <p>This dashboard provides comprehensive visibility into your Snowflake account usage including:</p>
            <ul style="color: inherit;">
                <li>Account type and credit balance</li>
                <li>Warehouse credit consumption</li>
                <li>Top expensive queries</li>
                <li>Stage storage exploration</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
    
    if st.session_state.conn:
        display_account_overview()
        display_warehouse_usage()
        display_top_queries()
        display_stage_explorer()
    else:
        st.warning("⚠️ Please connect to Snowflake using the sidebar")

if __name__ == "__main__":
    main()
