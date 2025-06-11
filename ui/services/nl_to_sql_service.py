import time
from flask import Blueprint, request, jsonify
import json
import logging
import mysql.connector
import sqlite3
import os
import traceback
from datetime import datetime
from google import genai
from google.genai import types
import re
from . import stream_manager
os.makedirs('logs', exist_ok=True)
logging.basicConfig(filename='logs/nl_to_sql_service.log', level=logging.
    INFO, format=
    '%(asctime)s - %(levelname)s - %(pathname)s:%(lineno)d - %(message)s')
logger = logging.getLogger(__name__)
bp = Blueprint('nl_to_sql', __name__, url_prefix='/api/nl-to-sql')
DB_CONFIG = {
    'host': 'YOUR_DATABASE_HOST',
    'port': 'YOUR_DATABASE_POST',
    'user': 'YOUR_DATABASE_USER',
    'password': 'YOUR_DATABASE_PASSWORD',
    'database': 'YOUR_DATABASE_NAME'
}

SQLITE_DB_PATH = '../.venv/BIRD'
FLASH_CLIENT = genai.Client(project="your-gcp-project-id")
FLASH_MODEL = 'gemini-2.0-flash-001'
streaming_id = None
PROMPT_DIR = '../resources/prompts/'
SCHEMA_FILE_PATH = '../data/BIRD_table_schema_info.json'
COMPACT_STATS_FILE_PATH = '../data/compact_dataset_stats.json'
CLEAN_SCHEMA_FILE_PATH = '../data/clean_and_must_follow_schema_details.json'
SQL_GENERATION_PROMPT_PATH = os.path.join(PROMPT_DIR,
    'sql_generation_prompt.json')
SQL_RETRY_PROMPT_PATH = os.path.join(PROMPT_DIR, 'sql_retry_prompt.json')
os.makedirs(PROMPT_DIR, exist_ok=True)


def get_db_connection():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except mysql.connector.Error as e:
        logger.error(f'Database connection error: {str(e)}')
        raise


def get_sqlite_connection():
    try:
        conn = sqlite3.connect(SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        logger.error(f'SQLite connection error: {str(e)}')
        raise


def load_files():
    try:
        with open(SCHEMA_FILE_PATH, 'r') as f:
            schema_data = json.load(f)
        try:
            with open(CLEAN_SCHEMA_FILE_PATH, 'r') as f:
                clean_schema_data = json.load(f)
                logger.info('Successfully loaded clean schema details')
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f'Failed to load clean schema details: {str(e)}')
            clean_schema_data = {}
        try:
            with open(COMPACT_STATS_FILE_PATH, 'r') as f:
                compact_stats_data = json.load(f)
                logger.info('Successfully loaded compact dataset statistics')
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(
                f'Failed to load compact dataset statistics: {str(e)}')
            compact_stats_data = {}
        try:
            if not os.path.exists(SQL_GENERATION_PROMPT_PATH):
                default_sql_prompt = {'system_message':
                    'You are a database expert who knows every intricacy of SQL query generation.'
                    , 'task_description':
                    'Generate a SQL query to answer the following question.',
                    'sqlite_guidelines': [
                    'SQLite does not support RIGHT JOIN or FULL OUTER JOIN - use LEFT JOIN instead'
                    ,
                    'Use double quotes for identifiers (table and column names) and single quotes for string literals'
                    ,
                    'For date operations, use SQLite date functions like strftime()'
                    , 'SQLite supports LIMIT and OFFSET for pagination',
                    'SQLite does not support advanced window functions - keep aggregations simple'
                    ,
                    'IMPORTANT: Always include LIMIT 10 when retrieving lists of data'
                    ,
                    'Use clear column aliases for readability (e.g., COUNT(*) AS total_count)'
                    ], 'column_name_rules': [
                    'Use EXACTLY the column names as they appear in the schema - check each column name carefully'
                    , 'Do NOT use spaces in column names',
                    'Always double-check aliases when using table.column notation'
                    ,
                    'Verify all column names against the schema before finalizing any query'
                    ]}
                with open(SQL_GENERATION_PROMPT_PATH, 'w') as f:
                    json.dump(default_sql_prompt, f, indent=2)
            if not os.path.exists(SQL_RETRY_PROMPT_PATH):
                default_retry_prompt = {'system_message':
                    'You are a database expert who needs to fix a SQL query that failed.'
                    , 'task_description':
                    'Analyze the error message provided and fix the SQL query that failed.'
                    , 'sqlite_guidelines': [
                    'SQLite does not support RIGHT JOIN or FULL OUTER JOIN - use LEFT JOIN instead'
                    ,
                    'Use double quotes for identifiers (table and column names) and single quotes for string literals'
                    ,
                    'For date operations, use SQLite date functions like strftime()'
                    , 'SQLite supports LIMIT and OFFSET for pagination',
                    'SQLite does not support advanced window functions - keep aggregations simple'
                    ,
                    'IMPORTANT: Always include LIMIT 10 when retrieving lists of data'
                    ,
                    'Use clear column aliases for readability (e.g., COUNT(*) AS total_count)'
                    ], 'column_name_rules': [
                    'Use EXACTLY the column names as they appear in the schema - check each column name carefully'
                    , 'Do NOT use spaces in column names',
                    'Always double-check aliases when using table.column notation'
                    ,
                    'Verify all column names against the schema before finalizing any query'
                    ], 'common_errors_to_fix': [
                    'Incorrect column or table names',
                    'Missing quotes around identifiers with spaces',
                    'Invalid SQL syntax', 'Type mismatches in comparisons',
                    'Missing or incorrect join conditions'],
                    'analysis_instructions': [
                    'Carefully examine the error message to identify the exact issue'
                    , 'Check if column or table names are incorrect',
                    'Verify that all syntax is valid for SQLite',
                    'Ensure all column references are properly quoted if they contain spaces'
                    ,
                    'Check for type mismatches in comparisons or calculations']
                    }
                with open(SQL_RETRY_PROMPT_PATH, 'w') as f:
                    json.dump(default_retry_prompt, f, indent=2)
            with open(SQL_GENERATION_PROMPT_PATH, 'r') as f:
                sql_generation_prompt = json.load(f)
            with open(SQL_RETRY_PROMPT_PATH, 'r') as f:
                sql_retry_prompt = json.load(f)
            prompts = {'sql_generation': sql_generation_prompt, 'sql_retry':
                sql_retry_prompt}
        except Exception as e:
            logger.error(f'Error loading prompt files: {str(e)}')
            prompts = {'sql_generation': {'system_message': 'Generate SQL'},
                'sql_retry': {'system_message': 'Fix SQL'}}
        return schema_data, clean_schema_data, compact_stats_data, prompts
    except Exception as e:
        logger.error(f'Error loading files: {str(e)}')
        return {'tables': []}, {}, {}, {}


def get_flash_sql_response_schema():
    return {'type': 'OBJECT', 'properties': {'thought_process': {'type':
        'STRING'}, 'sql_query': {'type': 'STRING'}, 'explanation': {'type':
        'STRING'}}, 'required': ['thought_process', 'sql_query', 'explanation']
        }


def call_flash_api(prompt, response_schema, max_tokens=8192):
    try:
        logger.info('Calling Flash (Gemini) API')
        logger.info(f'Prompt (abbreviated): {prompt[:200]}...')
        generate_content_config = types.GenerateContentConfig(temperature=0,
            top_p=0.95, max_output_tokens=max_tokens, response_modalities=[
            'TEXT'], safety_settings=[types.SafetySetting(category=
            'HARM_CATEGORY_HATE_SPEECH', threshold='OFF'), types.
            SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT',
            threshold='OFF'), types.SafetySetting(category=
            'HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='OFF'), types.
            SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold=
            'OFF')], response_mime_type='application/json', response_schema
            =response_schema)
        contents = [types.Content(role='user', parts=[types.Part.from_text(
            text=prompt)])]
        response_text = ''
        for chunk in FLASH_CLIENT.models.generate_content_stream(model=
            FLASH_MODEL, contents=contents, config=generate_content_config):
            chunk_text = chunk.text if chunk.text else ''
            response_text += chunk_text
        logger.info(
            f'Flash API response received: {len(response_text)} characters')
        logger.info(f'Response (abbreviated): {response_text[:200]}...')
        try:
            parsed_response = json.loads(response_text)
            return parsed_response
        except json.JSONDecodeError as e:
            logger.error(f'Failed to parse JSON from Flash response: {str(e)}')
            json_start = response_text.find('```json')
            if json_start != -1:
                json_start += 7
                json_end = response_text.find('```', json_start)
                if json_end != -1:
                    json_str = response_text[json_start:json_end].strip()
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError:
                        pass
            json_start = response_text.find('```')
            if json_start != -1:
                json_start += 3
                json_end = response_text.find('```', json_start)
                if json_end != -1:
                    json_str = response_text[json_start:json_end].strip()
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError:
                        pass
            logger.error(f'Raw response: {response_text[:1000]}...')
            return None
    except Exception as e:
        logger.error(f'Error calling Flash API: {str(e)}')
        logger.error(traceback.format_exc())
        return None


def execute_sql_query(sql_query):
    try:
        sqlite_conn = get_sqlite_connection()
        cursor = sqlite_conn.cursor()
        start_time = time.time()
        cursor.execute(sql_query)
        rows = cursor.fetchall()
        elapsed_time = time.time() - start_time
        column_names = [description[0] for description in cursor.description
            ] if cursor.description else []
        formatted_results = []
        for row in rows:
            row_dict = {}
            for i, column_name in enumerate(column_names):
                value = row[i]
                row_dict[column_name] = value
            formatted_results.append(row_dict)
        cursor.close()
        sqlite_conn.close()
        return {'success': True, 'result_rows': formatted_results,
            'column_names': column_names, 'row_count': len(rows),
            'elapsed_time': elapsed_time}
    except sqlite3.Error as e:
        logger.error(f'SQLite error executing query: {str(e)}')
        return {'success': False, 'error': str(e), 'traceback': traceback.
            format_exc()}


def generate_sql_with_flash(question, schema_data, clean_schema_data,
    compact_stats_data, prompts, user_id=None, dataset_id=None, is_retry=
    False, error_info=None):
    try:
        prompt_data = prompts.get('sql_retry' if is_retry else
            'sql_generation', {})
        prompt = f"""
{prompt_data.get('system_message', 'You are a database expert who knows every intricacy of SQL query generation for SQLite databases.')}

{prompt_data.get('task_description', 'Generate a SQL query to answer the following question:')}
"{question}"

{json.dumps(schema_data, indent=2)}

{json.dumps(clean_schema_data, indent=2)}

{json.dumps(compact_stats_data, indent=2)}

"""
        for guideline in prompt_data.get('sqlite_guidelines', [
            'SQLite does not support RIGHT JOIN or FULL OUTER JOIN - use LEFT JOIN instead'
            ,
            'Use double quotes for identifiers (table and column names) and single quotes for string literals'
            ,
            'For date operations, use SQLite date functions like strftime()',
            'SQLite supports LIMIT and OFFSET for pagination',
            'SQLite does not support advanced window functions - keep aggregations simple'
            ,
            'IMPORTANT: Always include LIMIT 10 when retrieving lists of data',
            'Use clear column aliases for readability (e.g., COUNT(*) AS total_count)'
            ]):
            prompt += f'- {guideline}\n'
        prompt += '\n# CRITICAL: Column Name Rules\n'
        for rule in prompt_data.get('column_name_rules', [
            'Use EXACTLY the column names as they appear in the schema - check each column name carefully'
            , 'Do NOT use spaces in column names',
            'Always double-check aliases when using table.column notation',
            'Verify all column names against the schema before finalizing any query'
            ]):
            prompt += f'- {rule}\n'
        if is_retry and error_info:
            prompt += f"""
```sql
{error_info.get('previous_sql', '')}
```

{error_info.get('error', '')}

{error_info.get('traceback', '')}

"""
            for error in prompt_data.get('common_errors_to_fix', [
                'Incorrect column or table names',
                'Missing quotes around identifiers with spaces',
                'Invalid SQL syntax', 'Type mismatches in comparisons',
                'Missing or incorrect join conditions']):
                prompt += f'- {error}\n'
            prompt += '\n# Analysis Instructions\n'
            for instruction in prompt_data.get('analysis_instructions', [
                'Carefully examine the error message to identify the exact issue'
                , 'Check if column or table names are incorrect',
                'Verify that all syntax is valid for SQLite',
                'Ensure all column references are properly quoted if they contain spaces'
                , 'Check for type mismatches in comparisons or calculations']):
                prompt += f'- {instruction}\n'
        response_schema = get_flash_sql_response_schema()
        if user_id and streaming_id:
            stream_manager.update_stream(user_id, streaming_id, 'nl_to_sql',
                'model_api_call',
                'Asking AI to convert your question to SQL', 40)
        response_data = call_flash_api(prompt, response_schema)
        if not response_data:
            return None, None, 'Failed to get response from Flash API'
        sql = response_data.get('sql_query', '')
        if user_id and streaming_id:
            stream_manager.update_stream(user_id, streaming_id, 'nl_to_sql',
                'sql_generated', 'SQL query generated successfully', 50)
        thought_process = response_data.get('thought_process', '')
        explanation = response_data.get('explanation', '')
        return sql, thought_process, explanation
    except Exception as e:
        logger.error(f'Error generating SQL: {str(e)}')
        logger.error(traceback.format_exc())
        return None, None, f'Error: {str(e)}'


def format_answer_from_results(results):
    if not results or not isinstance(results, list):
        return 'No results available.'
    if len(results) == 1:
        row = results[0]
        if len(row) == 1:
            key = list(row.keys())[0]
            return f'The {key} is {row[key]}.'
        else:
            parts = []
            for key, value in row.items():
                parts.append(f'{key}: {value}')
            return 'Result: ' + ', '.join(parts)
    else:
        if len(results) > 10:
            rows_text = f'Found {len(results)} rows. Here are the first 10:'
            display_results = results[:10]
        else:
            rows_text = f'Found {len(results)} rows:'
            display_results = results
        answer = (
            f"<p>{rows_text}</p><table class='table table-striped'><thead><tr>"
            )
        headers = list(display_results[0].keys())
        for header in headers:
            answer += f'<th>{header}</th>'
        answer += '</tr></thead><tbody>'
        for row in display_results:
            answer += '<tr>'
            for header in headers:
                answer += f"<td>{row.get(header, '')}</td>"
            answer += '</tr>'
        answer += '</tbody></table>'
        if len(results) > 10:
            answer += '<p><em>Note: Only showing the first 10 rows.</em></p>'
        return answer


def create_dataset_record(conn, question, decision):
    try:
        cursor = conn.cursor()
        question_json = json.dumps({'text': question})
        decision_json = json.dumps({'text': decision})
        insert_query = """
        INSERT INTO dataset 
        (question, decision, status, version, source)
        VALUES (%s, %s, %s, %s, %s)
        """
        cursor.execute(insert_query, (question_json, decision_json,
            'active', 1, 'web_interface'))
        dataset_id = cursor.lastrowid
        conn.commit()
        cursor.close()
        logger.info(f'Created new dataset record with ID {dataset_id}')
        return dataset_id
    except Exception as e:
        logger.error(f'Error creating dataset record: {str(e)}')
        conn.rollback()
        raise


def create_query_record(conn, dataset_id, question, query_model,
    sequence_index, sql, thought_process, explanation, execution_details,
    framework='', framework_factor='', sql_gen_status='a1_done'):
    try:
        cursor = conn.cursor()
        cot_details = {'thought_process': thought_process, 'explanation':
            explanation}
        sql_options = {'sql_query': sql}
        if not framework:
            framework_details = {}
        else:
            framework_details = {'type': framework}
        insert_query = """
        INSERT INTO query 
        (dataset_id, query_model, NL_question, model_query_sequence_index, 
         current_sql_options, COT_details, execution_details,
         framework_details, framework_contribution_factor_name,
         sql_generation_status, execution_status, status, version)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(insert_query, (dataset_id, query_model, question,
            sequence_index, json.dumps(sql_options), json.dumps(cot_details
            ), json.dumps(execution_details) if execution_details else None,
            json.dumps(framework_details), framework_factor, sql_gen_status,
            'success' if execution_details and execution_details.get(
            'success') else 'failed', 'active', 1))
        query_id = cursor.lastrowid
        conn.commit()
        cursor.close()
        logger.info(
            f'Created new query record with ID {query_id}, status={sql_gen_status}'
            )
        return query_id
    except Exception as e:
        logger.error(f'Error creating query record: {str(e)}')
        conn.rollback()
        raise


@bp.route('', methods=['POST'])
def generate_sql():
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        dataset_id = data.get('dataset_id')
        user_id = data.get('user_id')
        global streaming_id
        streaming_id = data.get('streaming_id') or data.get('dataset_id')
        if streaming_id and user_id:
            stream_manager.update_stream(user_id, streaming_id, 'nl_to_sql',
                'starting', 'Starting SQL generation for your question', 0)
        question = data.get('question')
        decision = data.get('decision', '')
        if not question:
            return jsonify({'error': 'Question is required'}), 400
        if not user_id:
            return jsonify({'error': 'User ID is required'}), 400
        logger.info(
            f'NL to SQL request for dataset_id={dataset_id}, user_id={user_id}'
            )
        logger.info(f'Question: {question}')
        logger.info(f'Decision: {decision}')
        conn = get_db_connection()
        if not dataset_id:
            try:
                dataset_id = create_dataset_record(conn, question, decision)
                logger.info(f'Created new dataset with ID {dataset_id}')
            except Exception as e:
                logger.error(f'Failed to create dataset: {str(e)}')
                conn.close()
                return jsonify({'success': False, 'error':
                    f'Failed to create dataset: {str(e)}'}), 500
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT q.id, q.NL_question, q.COT_details, q.current_sql_options, q.execution_details 
            FROM query q
            WHERE q.dataset_id = %s 
            AND q.query_model = 'question_to_sql'
            AND q.NL_question = %s
            AND (q.sql_generation_status = 'a1_done' OR q.sql_generation_status = 'a2_done')
            AND q.execution_status = 'success'
            AND q.status = 'active'
            LIMIT 1
        """
            , (dataset_id, question))
        query_record = cursor.fetchone()
        cursor.close()
        if query_record:
            logger.info(
                f'Found existing query for dataset_id={dataset_id}, question={question}'
                )
            current_sql_options = json.loads(query_record[
                'current_sql_options']) if query_record['current_sql_options'
                ] else {}
            execution_details = json.loads(query_record['execution_details']
                ) if query_record['execution_details'] else {}
            COT_details = json.loads(query_record['COT_details']
                ) if query_record['COT_details'] else {}
            sql = current_sql_options.get('sql_query', '')
            results = execution_details.get('result_rows', [])
            reasoning = COT_details.get('explanation', '')
            answer = format_answer_from_results(results)
            conn.close()
            return jsonify({'success': True, 'dataset_id': dataset_id,
                'sql': sql, 'reasoning': reasoning, 'answer': answer,
                'results': results, 'query_id': query_record['id']})
        logger.info(
            f'No existing query found. Generating new SQL for dataset_id={dataset_id}, question={question}'
            )
        schema_data, clean_schema_data, compact_stats_data, prompts = (
            load_files())
        if streaming_id and user_id:
            stream_manager.update_stream(user_id, streaming_id, 'nl_to_sql',
                'query_generation', 'Getting SQL from NL2SQL', 30)
        sql, thought_process, explanation = generate_sql_with_flash(question,
            schema_data, clean_schema_data, compact_stats_data, prompts,
            user_id, dataset_id)
        if not sql:
            conn.close()
            return jsonify({'success': False, 'error':
                'Failed to generate SQL query', 'message': explanation or
                'Unknown error occurred'}), 500
        logger.info(f'Generated SQL: {sql}')
        if user_id and streaming_id:
            stream_manager.update_stream(user_id, streaming_id, 'nl_to_sql',
                'executing_sql', 'Executing SQL query against database', 60)
        query_id = create_query_record(conn, dataset_id, question,
            'question_to_sql', 1, sql, thought_process, explanation, None,
            sql_gen_status='pending')
        execution_result = execute_sql_query(sql)
        cursor = conn.cursor()
        update_query = """
        UPDATE query
        SET execution_details = %s,
            sql_generation_status = %s,
            execution_status = %s
        WHERE id = %s
        """
        cursor.execute(update_query, (json.dumps(execution_result),
            'a1_done', 'success' if execution_result.get('success') else
            'failed', query_id))
        conn.commit()
        cursor.close()
        if user_id and streaming_id:
            stream_manager.update_stream(user_id, streaming_id, 'nl_to_sql',
                'sql_executed', 'SQL executed, processing results', 70)
        if not execution_result.get('success'):
            logger.info(
                f'SQL execution failed. Retrying with error information.')
            error_info = {'previous_sql': sql, 'error': execution_result.
                get('error', ''), 'traceback': execution_result.get(
                'traceback', '')}
            if user_id and streaming_id:
                stream_manager.update_stream(user_id, streaming_id,
                    'nl_to_sql', 'retry_sql',
                    'Refining SQL query for correct results', 90)
            sql, thought_process, explanation = generate_sql_with_flash(
                question, schema_data, clean_schema_data,
                compact_stats_data, prompts, user_id, dataset_id, is_retry=
                True, error_info=error_info)
            if not sql:
                conn.close()
                return jsonify({'success': False, 'error':
                    'Failed to generate valid SQL query after retry',
                    'message': explanation or 'Unknown error occurred'}), 500
            logger.info(f'Retry SQL: {sql}')
            execution_result = execute_sql_query(sql)
        if not execution_result.get('success'):
            cursor = conn.cursor()
            update_query = """
            UPDATE query
            SET current_sql_options = %s,
                COT_details = %s,
                execution_details = %s,
                sql_generation_status = %s,
                execution_status = %s
            WHERE id = %s
            """
            cursor.execute(update_query, (json.dumps({'sql_query': sql}),
                json.dumps({'thought_process': thought_process,
                'explanation': explanation}), json.dumps(execution_result),
                'a2_done', 'failed', query_id))
            conn.commit()
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'dataset_id': dataset_id,
                'error':
                'Sorry, we could not execute this query against the available dataset'
                , 'message':
                'The query could not be executed with the current dataset schema'
                , 'sql': sql, 'reasoning': explanation, 'query_id': query_id}
                ), 500
        logger.info(
            f"SQL executed successfully: {execution_result.get('row_count')} rows returned"
            )
        cursor = conn.cursor()
        update_query = """
        UPDATE query
        SET current_sql_options = %s,
            COT_details = %s,
            execution_details = %s,
            sql_generation_status = %s,
            execution_status = %s
        WHERE id = %s
        """
        cursor.execute(update_query, (json.dumps({'sql_query': sql}), json.
            dumps({'thought_process': thought_process, 'explanation':
            explanation}), json.dumps(execution_result), 'a2_done',
            'success', query_id))
        conn.commit()
        cursor.close()
        results = execution_result.get('result_rows', [])
        answer = format_answer_from_results(results)
        conn.close()
        return jsonify({'success': True, 'dataset_id': dataset_id, 'sql':
            sql, 'reasoning': explanation, 'answer': answer, 'results':
            results, 'query_id': query_id})
    except Exception as e:
        logger.error(f'Error in generate_sql: {str(e)}')
        logger.error(traceback.format_exc())
        if user_id and streaming_id:
            stream_manager.update_stream(user_id, streaming_id, 'nl_to_sql',
                'error', f'Error: {str(e)}', 100)
        return jsonify({'error': str(e)}), 500
