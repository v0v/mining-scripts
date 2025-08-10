from pathlib import Path
import psycopg2
from psycopg2 import Error
from datetime import datetime
import re
from bs4 import BeautifulSoup

DEBUG = 1

# Database connection parameters
db_params = {
    "dbname": "fogplay",
    "user": "postgres",
    "password": "postgres",
    "host": "192.168.1.1",
    "port": "5432"
}

# Path to your .xls file (which contains HTML content)
downloads_folder = Path.home() / "Downloads"
html_file_path = str(downloads_folder) + r"\sessions.xls"
if DEBUG > 0: print(html_file_path)

# Existing table creation queries
create_sessions_table_query = """
CREATE TABLE IF NOT EXISTS game_sessions (
    id VARCHAR(255) PRIMARY KEY,
    pc_name VARCHAR(50),
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    duration INTERVAL,
    status VARCHAR(50),
    income DECIMAL(10, 2),
    payment_status VARCHAR(50),
    payment_date TIMESTAMP,
    payment_id VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

create_matched_table_query = """
CREATE TABLE IF NOT EXISTS matched_sessions (
    session_id VARCHAR(255),
    pc_name VARCHAR(50),
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    duration INTERVAL,
    income DECIMAL(10, 2),
    game_name VARCHAR(50),
    game_start_time TIMESTAMP,
    PRIMARY KEY (session_id, game_start_time)
);
"""

# Existing upsert query
upsert_sessions_query = """
INSERT INTO game_sessions (
    id, pc_name, start_time, end_time, duration, status, 
    income, payment_status, payment_date, payment_id
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (id) DO UPDATE SET
    pc_name = EXCLUDED.pc_name,
    start_time = EXCLUDED.start_time,
    end_time = EXCLUDED.end_time,
    duration = EXCLUDED.duration,
    status = EXCLUDED.status,
    income = EXCLUDED.income,
    payment_status = EXCLUDED.payment_status,
    payment_date = EXCLUDED.payment_date,
    payment_id = EXCLUDED.payment_id,
    created_at = CURRENT_TIMESTAMP;
"""

# Updated match sessions query with unmatched handling
match_sessions_query = """
INSERT INTO matched_sessions (
    session_id, pc_name, start_time, end_time, duration, income, game_name, game_start_time
)
SELECT 
    session_id,
    pc_name,
    start_time,
    end_time,
    duration,
    income,
    COALESCE(last_game_name, 'unmatched') AS game_name,
    COALESCE(game_start_time, start_time) AS game_start_time
FROM (
    SELECT DISTINCT
        s.id AS session_id,
        s.pc_name,
        s.start_time,
        s.end_time,
        s.duration,
        s.income,
        FIRST_VALUE(e.value) OVER (
            PARTITION BY s.id
            ORDER BY e.timestamp DESC
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS last_game_name,
        FIRST_VALUE(e.timestamp) OVER (
            PARTITION BY s.id
            ORDER BY e.timestamp DESC
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS game_start_time
    FROM 
        game_sessions s
    LEFT JOIN 
        events e ON e.timestamp BETWEEN (s.start_time - INTERVAL '200 seconds') AND s.end_time 
               AND s.pc_name = e.server
               AND e.event = 'new_game_started'
    WHERE 
        s.duration > INTERVAL '1 minute'
) sub
ON CONFLICT ON CONSTRAINT session_id DO UPDATE
    SET game_name = EXCLUDED.game_name;
"""

# Cleaning functions (unchanged)
def clean_duration(duration_str):
    if 'мин.' in duration_str.lower():
        minutes = int(re.search(r'\d+', duration_str).group())
        return f"{minutes} minutes"
    return "0 minutes"

def clean_timestamp(timestamp_str):
    if timestamp_str == '-' or timestamp_str is None or timestamp_str.strip() == '':
        return None
    try:
        # First try parsing with timezone (ISO 8601 format)
        try:
            return datetime.fromisoformat(timestamp_str)
        except ValueError:
            # Fall back to the format without timezone if ISO parsing fails
            return datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
    except ValueError as e:
        print(f"Error parsing timestamp '{timestamp_str}': {e}")
        return None

def clean_payment_id(payment_id):
    if payment_id == '-' or payment_id is None or payment_id.strip() == '':
        return None
    return str(payment_id)

def clean_income(income_str):
    if income_str == '0.00 руб.' or income_str is None or income_str.strip() == '':
        return 0.00
    return float(re.search(r'[\d.]+', str(income_str)).group())

def parse_html_sessions(file_path):
    sessions = []
    with open(file_path, 'r', encoding='utf-8') as file:
        soup = BeautifulSoup(file.read(), 'html.parser')
        table = soup.find('table')
        if not table:
            raise ValueError("No table found in file.")
        for row in table.find_all('tr')[1:]:
            cols = row.find_all('td')
            if len(cols) == 10:
                session = {
                    'ID': cols[0].text.strip(),
                    'PC Name': cols[1].text.strip(),
                    'Start Time': cols[2].text.strip(),
                    'End Time': cols[3].text.strip(),
                    'Duration': cols[4].text.strip(),
                    'Status': cols[5].text.strip(),
                    'Income': cols[6].text.strip(),
                    'Payment Status': cols[7].text.strip(),
                    'Payment Date': cols[8].text.strip(),
                    'Payment ID': cols[9].text.strip()
                }
                sessions.append(session)
    return sessions

def import_game_sessions():
    try:
        connection = psycopg2.connect(**db_params)
        cursor = connection.cursor()

        # Create tables
        cursor.execute(create_sessions_table_query)
        cursor.execute(create_matched_table_query)
        connection.commit()
        print("Tables created or already exist.")

        # Parse and import sessions
        sessions_data = parse_html_sessions(html_file_path)
        for session in sessions_data:
            session_id = str(session['ID'])
            pc_name = str(session['PC Name'])
            start_time = clean_timestamp(session['Start Time'])
            end_time = clean_timestamp(session['End Time'])
            duration = clean_duration(session['Duration'])
            status = str(session['Status'])
            income = clean_income(session['Income'])
            payment_status = str(session['Payment Status'])
            payment_date = clean_timestamp(session['Payment Date'])
            payment_id = clean_payment_id(session['Payment ID'])
            data_tuple = (
                session_id, pc_name, start_time, end_time, duration, status,
                income, payment_status, payment_date, payment_id
            )
            if DEBUG > 0: print(data_tuple)
            
            cursor.execute(upsert_sessions_query, data_tuple)
            connection.commit()
            
        # Match sessions with events and handle unmatched
        cursor.execute(match_sessions_query)
        connection.commit()
        print(f"Successfully imported {len(sessions_data)} game sessions and matched with events.")

    except (Exception, Error) as error:
        print(f"Error: {error}")
        if 'connection' in locals():
            connection.rollback()

    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'connection' in locals():
            connection.close()
            print("Database connection closed.")

if __name__ == "__main__":
    import_game_sessions()