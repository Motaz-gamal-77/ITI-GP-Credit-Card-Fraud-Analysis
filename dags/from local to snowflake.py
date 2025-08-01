from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.task_group import TaskGroup
from datetime import timedelta,datetime
import snowflake.connector
import psycopg2
import os
import csv
import pandas as pd


# connect to Postgres
def connect_to_Postgres():
    print("Connecting to Billing_DWH..... ")
    conn = psycopg2.connect(
        user='spark',
        password='spark',
        host='postgres_v2',
        port='5432',         
        database='sparkdb'
    )
    cur = conn.cursor()
    return conn ,cur


# connect to Snowflake
def connect_to_snowflake():
    # Connect to Snowflake
    conn = snowflake.connector.connect(
        user='MOATAZGAMAL710',
        password='@123456789123Dwh',  # Ideally use os.environ.get('snowflake_pass')
        account='YREDIGW-DB28773',
        warehouse='COMPUTE_WH',
        database='FRAUD_DWH',
        schema='PUBLIC'
    )
    cur = conn.cursor()
    return cur , conn



# Function to extract data from Postgres and save it to a CSV file
def extract_data_from_postgres_and_save_it_to_csv(querey, file_name):
    conn, cur = connect_to_Postgres()
    try:
        df = pd.read_sql(querey, conn)
        df.to_csv(f'/opt/airflow/data/stagging/{file_name}.csv', index=False)
    finally:
        cur.close() 
        conn.close()

# Function to load CSV file into Snowflake staging area
def loaad_csv_to_staging_area(CSV_PATH):
    cursor , conn = connect_to_snowflake()
    try:
        # Upload local file to internal stage
        cursor.execute(f"PUT file://{CSV_PATH} @AIRFLOW_STAGE OVERWRITE = TRUE")
    finally:
        cursor.close()

# Function to remove duplicates from a table in Snowflake
def remove_duplicates_from(query1,query2,query3,query4):
    cursor , conn = connect_to_snowflake()
    cursor.execute(query1)  # Create temporary table with distinct records
    cursor.execute(query2)  # Truncate the original table
    cursor.execute(query3)  # Insert distinct records back into the original table
    cursor.execute(query4)  # Drop the temporary table
    conn.commit()  # Commit the changes
    cursor.close()

# Function to load CSV data into Snowflake staging area and then into targeted table
def load_csv_to_snowflake(CSV_FILE_NAME,table_name):
    cursor , conn = connect_to_snowflake()
    try:
        # Load data from stage into table
        cursor.execute(f"""
            COPY INTO {table_name}
            FROM @AIRFLOW_STAGE/{CSV_FILE_NAME}
            FILE_FORMAT = (TYPE = 'CSV' FIELD_OPTIONALLY_ENCLOSED_BY = '"' SKIP_HEADER = 1)
            ON_ERROR = 'CONTINUE'
        """)
    finally:
        cursor.close()
        
# --------------------------------------------------------------------------------------- #
        
# Main DAG definition
with DAG(
    dag_id='list_snowflake_tables',
    start_date=datetime(2025, 7, 29),
    schedule_interval='0 1 * * *',
    catchup=False
) as dag:
    # --------------------------------------------------------------------------------------- #
    # extracting merschent data from postgres and saving it to csv
    merschant_data_extraction = PythonOperator(
        task_id='exrtract_merchant_data',
        python_callable=extract_data_from_postgres_and_save_it_to_csv,
        op_kwargs={
            'querey': "select distinct on (merchant_id) merchant_id, merchant, category, merch_long, merch_lat from transactions WHERE event_time::date = CURRENT_DATE - INTERVAL '1 day' ",
            'file_name': 'merchant_data'})
    
    # # extracting customer data from postgres and saving it to csv
    customer_data_extraction = PythonOperator(
        task_id='exrtract_customer_data',
        python_callable=extract_data_from_postgres_and_save_it_to_csv,
        op_kwargs={
            'querey': "select distinct on (customer_id) customer_id, cc_num, first, last, gender, dob, age, job, street, city, state, zip, lat, long, city_pop from transactions WHERE event_time::date = CURRENT_DATE - INTERVAL '1 day'",
            'file_name': 'customer_data'})
        
        
    # extracting transaction data from postgres and saving it to csv    
    transaction_data_extraction = PythonOperator(
        task_id='extract_transaction_data',
        python_callable=extract_data_from_postgres_and_save_it_to_csv,
        op_kwargs={
            'querey': "select trans_num, trans_date_trans_time, customer_id, merchant_id, amt, distance_km, is_fraud, unix_time from transactions WHERE event_time::date = CURRENT_DATE - INTERVAL '1 day'",
            'file_name': 'transaction_data'})

    # --------------------------------------------------------------------------------------- #
    # Loading merschent data into airflow staging area
    loding_merschent_csv_into_staging = PythonOperator(
        task_id='load_merchant_data_into_staging',
        python_callable=loaad_csv_to_staging_area,
        op_kwargs={'CSV_PATH': '/opt/airflow/data/stagging/merchant_data.csv'})

    # Loading customer data into airflow staging area
    loding_customer_csv_into_staging = PythonOperator(
        task_id='load_customer_data_into_staging',
        python_callable=loaad_csv_to_staging_area,
        op_kwargs={'CSV_PATH': '/opt/airflow/data/stagging/customer_data.csv'})

    # Loading transaction data into airflow staging area
    loding_transaction_csv_into_staging = PythonOperator(
        task_id='load_transaction_data_into_staging',
        python_callable=loaad_csv_to_staging_area,
        op_kwargs={'CSV_PATH': '/opt/airflow/data/stagging/transaction_data.csv'})

    # --------------------------------------------------------------------------------------- #
    # Loading merschent data from airflow staging area and then into targeted table
    merschent_dim_loding = PythonOperator(
        task_id='load_merchant_data',
        python_callable=load_csv_to_snowflake,
        op_kwargs={
            'CSV_FILE_NAME': 'merchant_data.csv',
            'table_name': 'merchant_Dim'
        }
    )

    # Loading customer data from airflow staging area and then into targeted table
    customer_dim_loding = PythonOperator(
        task_id='load_customer_data',
        python_callable=load_csv_to_snowflake,
        op_kwargs={
            'CSV_FILE_NAME': 'customer_data.csv',
            'table_name': 'customer_Dim'
        }
    )

    # Loading transaction data from airflow staging area and then into targeted table
    fact_loding = PythonOperator(
        task_id='load_fact_data',
        python_callable=load_csv_to_snowflake,
        op_kwargs={
            'CSV_FILE_NAME': 'transaction_data.csv',
            'table_name': 'transactions_fact'
        }
    )
    # --------------------------------------------------------------------------------------- #
    # Remove duplicates from customer_dim table
    remove_duplicates_customer_dim = PythonOperator(
        task_id='remove_duplicates_customer_dim',
        python_callable=remove_duplicates_from,
        op_kwargs={
            'query1': """ CREATE TEMPORARY TABLE temp_table AS SELECT DISTINCT * FROM customer_dim; """,
            'query2': """ TRUNCATE TABLE customer_dim; """,
            'query3': """ INSERT INTO customer_dim SELECT * FROM temp_table; """,
            'query4': """ DROP TABLE temp_table; """
        }
    )
    # Remove duplicates from merchant_dim table
    remove_duplicates_merchant_dim = PythonOperator(
        task_id='remove_duplicates_merchant_dim',
        python_callable=remove_duplicates_from,    
        op_kwargs={
            'query1': """ CREATE TEMPORARY TABLE temp_table2 AS SELECT DISTINCT * FROM merchant_dim; """,
            'query2': """ TRUNCATE TABLE merchant_dim; """,
            'query3': """ INSERT INTO merchant_dim SELECT * FROM temp_table2; """,
            'query4': """ DROP TABLE temp_table2; """
        }
    )





[merschant_data_extraction>>loding_merschent_csv_into_staging>> merschent_dim_loding >> remove_duplicates_merchant_dim, customer_data_extraction>>loding_customer_csv_into_staging>>customer_dim_loding>>remove_duplicates_customer_dim]>>transaction_data_extraction>>loding_transaction_csv_into_staging>>fact_loding
