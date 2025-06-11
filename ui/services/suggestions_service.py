from flask import Blueprint, request, jsonify
import json
import logging
import mysql.connector
import sqlite3
import os
import traceback
import re
from datetime import datetime
from google import genai
from google.genai import types
from . import stream_manager
os.makedirs('logs', exist_ok=True)
logging.basicConfig(filename='logs/suggestions_service.log', level=logging.
    INFO, format=
    '%(asctime)s - %(levelname)s - %(pathname)s:%(lineno)d - %(message)s')
logger = logging.getLogger(__name__)
bp = Blueprint('suggestions', __name__, url_prefix='/api/suggestions')
DB_CONFIG = {
    'host': 'YOUR_DATABASE_HOST',
    'port': 'YOUR_DATABASE_POST',
    'user': 'YOUR_DATABASE_USER',
    'password': 'YOUR_DATABASE_PASSWORD',
    'database': 'YOUR_DATABASE_NAME'
}

SQLITE_DB_PATH = '../.venv/BIRD'
streaming_id = None
FLASH_CLIENT = genai.Client(project="your-gcp-project-id")
FLASH_MODEL = 'gemini-2.0-flash-001'
PROMPT_DIR = '../resources/prompts/'
SCHEMA_FILE_PATH = '../data/BIRD_table_schema_info.json'
COMPACT_STATS_FILE_PATH = '../data/compact_dataset_stats.json'
CLEAN_SCHEMA_FILE_PATH = '../data/clean_and_must_follow_schema_details.json'
PILLAR_DIR = '../resources/question_guide_pillars/'
TOULMIN_FILE_PATH = os.path.join(PILLAR_DIR, 'toulmin_argument_structure.json')
DATASET_SCHEMA_FILE_PATH = os.path.join(PILLAR_DIR,
    'dataset_schema_based_patterns.json')
VULNERABILITY_FILE_PATH = os.path.join(PILLAR_DIR,
    'vulnerability_semantic_frames.json')
COUNTERARGUMENT_FILE_PATH = os.path.join(PILLAR_DIR,
    'preemptive-counterargument_pattern.json')
SUGGESTIONS_PROMPT_PATH = os.path.join(PROMPT_DIR, 'suggestions_prompt.json')
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
        pillar_files = {'toulmin': TOULMIN_FILE_PATH, 'dataset_schema':
            DATASET_SCHEMA_FILE_PATH, 'vulnerability':
            VULNERABILITY_FILE_PATH, 'counterargument':
            COUNTERARGUMENT_FILE_PATH}
        pillar_data = {}
        for key, path in pillar_files.items():
            if not os.path.exists(path):
                logger.warning(f'Pillar file not found: {path}')
                continue
            with open(path, 'r') as f:
                pillar_data[key] = json.load(f)
        try:
            if not os.path.exists(SUGGESTIONS_PROMPT_PATH):
                default_suggestions_prompt = {'system_message':
                    'You are a data science expert specialized in generating precise, insightful questions that lead to robust data-driven decisions.'
                    , 'task_description':
                    'For the given decision scenario, generate both a direct question and refinement questions.'
                    }
                with open(SUGGESTIONS_PROMPT_PATH, 'w') as f:
                    json.dump(default_suggestions_prompt, f, indent=2)
            if not os.path.exists(SQL_GENERATION_PROMPT_PATH):
                default_sql_prompt = {'system_message':
                    'You are a database expert who knows every intricacy of SQL query generation.'
                    , 'task_description':
                    'Generate a SQL query to answer the following question.'}
                with open(SQL_GENERATION_PROMPT_PATH, 'w') as f:
                    json.dump(default_sql_prompt, f, indent=2)
            if not os.path.exists(SQL_RETRY_PROMPT_PATH):
                default_retry_prompt = {'system_message':
                    'You are a database expert who needs to fix a SQL query that failed.'
                    , 'task_description':
                    'Analyze the error message provided and fix the SQL query that failed.'
                    }
                with open(SQL_RETRY_PROMPT_PATH, 'w') as f:
                    json.dump(default_retry_prompt, f, indent=2)
            with open(SUGGESTIONS_PROMPT_PATH, 'r') as f:
                suggestions_prompt = json.load(f)
            with open(SQL_GENERATION_PROMPT_PATH, 'r') as f:
                sql_generation_prompt = json.load(f)
            with open(SQL_RETRY_PROMPT_PATH, 'r') as f:
                sql_retry_prompt = json.load(f)
            prompts = {'suggestions': suggestions_prompt, 'sql_generation':
                sql_generation_prompt, 'sql_retry': sql_retry_prompt}
        except Exception as e:
            logger.error(f'Error loading prompt files: {str(e)}')
            prompts = {'suggestions': {'system_message':
                'Generate suggestions'}, 'sql_generation': {
                'system_message': 'Generate SQL'}, 'sql_retry': {
                'system_message': 'Fix SQL'}}
        return (schema_data, clean_schema_data, compact_stats_data,
            pillar_data, prompts)
    except Exception as e:
        logger.error(f'Error loading files: {str(e)}')
        return {'tables': []}, {}, {}, {}, {}


def get_dataset_details(conn, dataset_id):
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute('SELECT question, decision FROM dataset WHERE id = %s',
            (dataset_id,))
        record = cursor.fetchone()
        cursor.close()
        if record:
            question_json = json.loads(record['question']) if record['question'
                ] else {}
            decision_json = json.loads(record['decision']) if record['decision'
                ] else {}
            question_text = question_json.get('text', '')
            decision_text = decision_json.get('text', '')
            return question_text, decision_text
        else:
            return None, None
    except Exception as e:
        logger.error(f'Error getting dataset details: {str(e)}')
        return None, None


def get_flash_suggestions_response_schema():
    return {'type': 'OBJECT', 'properties': {'primary_question': {'type':
        'OBJECT', 'properties': {'question': {'type': 'STRING'},
        'explanation': {'type': 'STRING'}}, 'required': ['question',
        'explanation']}, 'refinement_questions': {'type': 'ARRAY', 'items':
        {'type': 'OBJECT', 'properties': {'question': {'type': 'STRING'},
        'pillar': {'type': 'STRING'}, 'component': {'type': 'STRING'},
        'purpose': {'type': 'STRING'}, 'bias_addressed': {'type': 'STRING'},
        'toulmin_component': {'type': 'STRING'}, 'rationale': {'type':
        'STRING'}}, 'required': ['question', 'pillar', 'component',
        'purpose', 'rationale']}}}, 'required': ['primary_question',
        'refinement_questions']}


def get_flash_sql_response_schema():
    return {'type': 'OBJECT', 'properties': {'thought_process': {'type':
        'STRING'}, 'sql_query': {'type': 'STRING'}, 'explanation': {'type':
        'STRING'}}, 'required': ['thought_process', 'sql_query', 'explanation']
        }


def call_flash_api(prompt, response_schema, max_tokens=8192, user_id=None,
    dataset_id=None):
    try:
        logger.info('Calling Flash (Gemini) API')
        if user_id and dataset_id:
            stream_manager.update_stream(user_id, dataset_id, 'suggestions',
                'model_api_call', 'Asking AI to generate suggestions', 40)
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


def generate_suggestions(question, decision, schema_data, clean_schema_data,
    compact_stats_data, pillar_data, prompts):
    try:
        vulnerability_data = pillar_data.get('vulnerability', {})
        vulnerability_categories = []
        if 'categories' in vulnerability_data:
            for category in vulnerability_data.get('categories', []):
                items = []
                for item in category.get('items', []):
                    items.append({'name': item.get('item_name', ''), 'id':
                        item.get('vulnerability_id', 0), 'description':
                        item.get('item_description', '')})
                vulnerability_categories.append({'name': category.get(
                    'category_name', ''), 'description': category.get(
                    'category_description', ''), 'items': items})
        toulmin_data = pillar_data.get('toulmin', {})
        toulmin_components = []
        if 'categories' in toulmin_data:
            for category in toulmin_data.get('categories', []):
                if category.get('category_name') == 'Argument Components':
                    for item in category.get('items', []):
                        sub_items = []
                        for sub_item in item.get('sub_items', []):
                            sub_items.append({'name': sub_item.get(
                                'aspect_name', ''), 'description': sub_item
                                .get('description', '')})
                        toulmin_components.append({'name': item.get(
                            'item_name', ''), 'description': item.get(
                            'item_description', ''), 'aspects': sub_items})
        dataset_schema_data = pillar_data.get('dataset_schema', {})
        schema_categories = []
        if 'categories' in dataset_schema_data:
            for category in dataset_schema_data.get('categories', []):
                item_details = []
                for item in category.get('items', []):
                    item_details.append({'name': item.get('item_name', ''),
                        'description': item.get('item_description', '')})
                schema_categories.append({'name': category.get(
                    'category_name', ''), 'description': category.get(
                    'category_description', ''), 'items': item_details})
        counterargument_data = pillar_data.get('counterargument', {})
        counterargument_categories = []
        if 'categories' in counterargument_data:
            for category in counterargument_data.get('categories', []):
                item_details = []
                for item in category.get('items', []):
                    item_details.append({'name': item.get('item_name', ''),
                        'description': item.get('item_description', '')})
                counterargument_categories.append({'name': category.get(
                    'category_name', ''), 'description': category.get(
                    'category_description', ''), 'items': item_details})
        suggestions_prompt = prompts.get('suggestions', {})
        prompt = f"""
{suggestions_prompt.get('system_message', 'You are a data science expert specialized in generating precise, insightful questions.')}

{suggestions_prompt.get('task_description', 'For the given decision scenario, generate questions that help make better decisions.')}

Original Question: "{question}"
Decision Context: "{decision}"

{json.dumps(schema_data, indent=2)}

{json.dumps(clean_schema_data, indent=2)}

{json.dumps(compact_stats_data, indent=2)}

{suggestions_prompt.get('hard_to_vary_definition', 'A hard-to-vary explanation has specific, data-constrained, non-arbitrary components.')}

"""
        if 'computational_algorithm' in suggestions_prompt:
            for step in suggestions_prompt.get('computational_algorithm', []):
                prompt += (
                    f"\n## {step.get('stage', '')}\n{step.get('description', '')}\n"
                    )
        else:
            prompt += """
Systematically analyze the decision scenario for potential cognitive biases using this reference:
"""
            prompt += json.dumps(vulnerability_categories, indent=2)
            prompt += (
                '\nFor each bias pattern identified, map to the database schema:\n'
                )
            prompt += json.dumps(schema_categories, indent=2)
            prompt += """
Classify each potential question according to these argument components:
"""
            prompt += json.dumps(toulmin_components, indent=2)
            prompt += """
Evaluate each potential question against these counter-argument frameworks:
"""
            prompt += json.dumps(counterargument_categories, indent=2)
            prompt += """
Produce a final set of questions by:
- Removing redundancies while preserving distinctness
- Ensuring comprehensive coverage across bias types and argument components
- Formulating questions in clear, precise natural language
- Ensuring each question contributes to a hard-to-vary explanation
"""
        prompt += '\n# Important Guidelines\n'
        for guideline in suggestions_prompt.get('important_guidelines', [
            'Generate 3-5 refinement questions that will help improve the decision-making process'
            ,
            'Each question must be clear, specific, and answerable using SQL queries against the database'
            ,
            'The questions should address different types of potential biases or limitations'
            , 'Ensure your response follows the required format exactly']):
            prompt += f'- {guideline}\n'
        response_schema = get_flash_suggestions_response_schema()
        response_data = call_flash_api(prompt, response_schema)
        if not response_data:
            return None
        primary_question = response_data.get('primary_question', {})
        refinement_questions = response_data.get('refinement_questions', [])
        suggestions = []
        if primary_question and 'question' in primary_question:
            primary = {'question': primary_question.get('question', ''),
                'pillar': 'Primary Question', 'component':
                'Direct Question', 'purpose': primary_question.get(
                'explanation', ''), 'rationale':
                'This question directly addresses the core information need.'}
            suggestions.append(primary)
        suggestions.extend(refinement_questions)
        return suggestions
    except Exception as e:
        logger.error(f'Error generating suggestions: {str(e)}')
        logger.error(traceback.format_exc())
        return None


def generate_sql_with_flash(question, schema_data, clean_schema_data,
    compact_stats_data, prompts, is_retry=False, error_info=None):
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
        response_data = call_flash_api(prompt, response_schema)
        if not response_data:
            return None, None, 'Failed to get response from Flash API'
        sql = response_data.get('sql_query', '')
        thought_process = response_data.get('thought_process', '')
        explanation = response_data.get('explanation', '')
        return sql, thought_process, explanation
    except Exception as e:
        logger.error(f'Error generating SQL: {str(e)}')
        logger.error(traceback.format_exc())
        return None, None, f'Error: {str(e)}'


def execute_sql_query(sql_query):
    import time
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


def update_query_with_execution_results(conn, query_id, sql,
    thought_process, explanation, execution_result, sql_gen_status='a1_done'):
    try:
        cursor = conn.cursor()
        cot_details = {'thought_process': thought_process, 'explanation':
            explanation}
        sql_options = {'sql_query': sql}
        update_query = """
        UPDATE query
        SET current_sql_options = %s,
            COT_details = %s,
            execution_details = %s,
            sql_generation_status = %s,
            execution_status = %s
        WHERE id = %s
        """
        cursor.execute(update_query, (json.dumps(sql_options), json.dumps(
            cot_details), json.dumps(execution_result), sql_gen_status, 
            'success' if execution_result.get('success') else 'failed',
            query_id))
        conn.commit()
        cursor.close()
        logger.info(
            f'Updated query record with ID {query_id}, status={sql_gen_status}'
            )
        return True
    except Exception as e:
        logger.error(f'Error updating query record: {str(e)}')
        conn.rollback()
        return False


@bp.route('', methods=['POST'])
def get_suggestions():
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        user_id = data.get('user_id')
        dataset_id = data.get('dataset_id')
        global streaming_id
        streaming_id = data.get('streaming_id')
        if not streaming_id:
            streaming_id = dataset_id
            if not streaming_id and user_id:
                import time
                streaming_id = f'{user_id}_{int(time.time())}'
        if user_id and streaming_id:
            stream_manager.update_stream(user_id, streaming_id,
                'suggestions', 'starting', 'Starting suggestion generation', 0)
        question = data.get('question')
        decision = data.get('decision', '')
        if not user_id:
            return jsonify({'error': 'User ID is required'}), 400
        if not question:
            return jsonify({'error': 'Question is required'}), 400
        logger.info(
            f"Suggestions request for user_id={user_id}, dataset_id={dataset_id or 'None'}"
            )
        logger.info(f'Question: {question}')
        logger.info(f'Decision: {decision}')
        if dataset_id:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT q.id, q.NL_question, q.model_query_sequence_index, 
                       q.framework_details, q.COT_details, q.current_sql_options, q.execution_details 
                FROM query q
                WHERE q.dataset_id = %s 
                AND q.query_model = 'baqr'
                AND (q.sql_generation_status = 'a1_done' OR q.sql_generation_status = 'a2_done') 
                AND q.execution_status = 'success'
                AND q.status = 'active'
            """
                , (dataset_id,))
            suggestion_records = cursor.fetchall()
            cursor.close()
            if suggestion_records:
                suggestions = []
                for record in suggestion_records:
                    try:
                        try:
                            if record.get('framework_details'):
                                framework_details = json.loads(record[
                                    'framework_details'])
                            else:
                                framework_details = {}
                        except (json.JSONDecodeError, TypeError) as e:
                            logger.warning(
                                f"Error parsing framework_details for record {record.get('id')}: {str(e)}"
                                )
                            framework_details = {}
                        suggestion = {'query_id': record['id'], 'question':
                            record['NL_question'], 'sequence_index': record
                            ['model_query_sequence_index'], 'purpose':
                            framework_details.get('purpose', ''),
                            'rationale': framework_details.get('rationale',
                            ''), 'pillar': framework_details.get('pillar',
                            'Refinement Question'), 'component':
                            framework_details.get('component', 'General')}
                        suggestions.append(suggestion)
                    except Exception as e:
                        logger.error(
                            f"Error processing suggestion record {record.get('id')}: {str(e)}"
                            )
                        logger.error(f'Record data: {record}')
                        continue
                conn.close()
                return jsonify({'success': True, 'suggestions': suggestions})
            if not question or not decision:
                question_text, decision_text = get_dataset_details(conn,
                    dataset_id)
                if question_text:
                    question = question_text
                if decision_text:
                    decision = decision_text
            conn.close()
        (schema_data, clean_schema_data, compact_stats_data, pillar_data,
            prompts) = load_files()
        logger.info(f'Generating new suggestions for question: {question}')
        if user_id and streaming_id:
            stream_manager.update_stream(user_id, streaming_id,
                'suggestions', 'generating_suggestions',
                'Custom crafting suggestions', 60)
        suggestions_data = generate_suggestions(question, decision,
            schema_data, clean_schema_data, compact_stats_data, pillar_data,
            prompts)
        if user_id and streaming_id:
            stream_manager.update_stream(user_id, streaming_id,
                'suggestions', 'processing_suggestions',
                'Processing generated suggestions', 70)
        if not suggestions_data:
            return jsonify({'success': False, 'error':
                'Failed to generate suggestions', 'message':
                'Could not generate suggestions for this question and decision'
                }), 500
        logger.info(f'Generated {len(suggestions_data)} suggestions')
        client_suggestions = []
        for idx, suggestion in enumerate(suggestions_data, start=1):
            client_suggestions.append({'temp_id': idx, 'question':
                suggestion.get('question', ''), 'pillar': suggestion.get(
                'pillar', ''), 'component': suggestion.get('component', ''),
                'purpose': suggestion.get('purpose', ''), 'rationale':
                suggestion.get('rationale', '')})
        if user_id and streaming_id:
            stream_manager.update_stream(user_id, streaming_id,
                'suggestions', 'complete', 'Suggestion generation complete',
                100)
        return jsonify({'success': True, 'suggestions': client_suggestions})
    except Exception as e:
        logger.error(f'Error in get_suggestions: {str(e)}')
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@bp.route('/process-selected', methods=['POST'])
def process_selected_suggestions():
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        dataset_id = data.get('dataset_id')
        user_id = data.get('user_id')
        selected_suggestions = data.get('selected_suggestions', [])
        if dataset_id and user_id:
            stream_manager.update_stream(user_id, dataset_id,
                'process_selected_suggestions', 'starting',
                'Processing your selected suggestions', 0)
        if not dataset_id:
            return jsonify({'error': 'Dataset ID is required'}), 400
        if not user_id:
            return jsonify({'error': 'User ID is required'}), 400
        if not selected_suggestions:
            return jsonify({'error': 'No suggestions selected'}), 400
        logger.info(
            f'Process selected suggestions for dataset_id={dataset_id}, user_id={user_id}'
            )
        logger.info(f'Selected suggestions: {len(selected_suggestions)}')
        conn = get_db_connection()
        schema_data, clean_schema_data, compact_stats_data, _, prompts = (
            load_files())
        answers = []
        queries = []
        for suggestion in selected_suggestions:
            try:
                total_suggestions = len(selected_suggestions)
                suggestion_progress_increment = 70 / max(total_suggestions, 1)
                question = suggestion.get('question', '')
                current_index = selected_suggestions.index(suggestion)
                progress = 20 + current_index * suggestion_progress_increment
                progress_message = (
                    f'Processing suggestion {current_index + 1} of {total_suggestions}'
                    )
                if user_id and dataset_id:
                    stream_manager.update_stream(user_id, dataset_id,
                        'process_selected_suggestions', 'progress',
                        progress_message, int(progress))
                if 'query_id' in suggestion and suggestion['query_id']:
                    query_id = suggestion['query_id']
                    logger.info(
                        f'Processing existing suggestion with query_id={query_id}'
                        )
                    cursor = conn.cursor(dictionary=True)
                    cursor.execute(
                        """
                        SELECT q.id, q.NL_question, q.COT_details, q.current_sql_options, 
                               q.execution_details, q.execution_status, q.framework_details
                        FROM query q
                        WHERE q.id = %s 
                        AND q.dataset_id = %s
                        AND q.status = 'active'
                    """
                        , (query_id, dataset_id))
                    query_record = cursor.fetchone()
                    cursor.close()
                    if not query_record:
                        logger.warning(
                            f'Query with id={query_id} not found in database')
                        answers.append({'query_id': query_id, 'question':
                            question, 'error': 'Query not found'})
                        queries.append({'query_id': query_id, 'error':
                            'Query not found'})
                        continue
                    if query_record.get('execution_status'
                        ) == 'success' and query_record.get('execution_details'
                        ) and query_record.get('current_sql_options'):
                        logger.info(
                            f'Using existing execution results for query_id={query_id}'
                            )
                        try:
                            current_sql_options = json.loads(query_record[
                                'current_sql_options']) if query_record.get(
                                'current_sql_options') else {}
                        except (json.JSONDecodeError, TypeError) as e:
                            logger.error(
                                f'Error parsing current_sql_options for query_id={query_id}: {str(e)}'
                                )
                            current_sql_options = {}
                        try:
                            execution_details = json.loads(query_record[
                                'execution_details']) if query_record.get(
                                'execution_details') else {}
                        except (json.JSONDecodeError, TypeError) as e:
                            logger.error(
                                f'Error parsing execution_details for query_id={query_id}: {str(e)}'
                                )
                            execution_details = {}
                        try:
                            cot_details = json.loads(query_record[
                                'COT_details']) if query_record.get(
                                'COT_details') else {}
                        except (json.JSONDecodeError, TypeError) as e:
                            logger.error(
                                f'Error parsing COT_details for query_id={query_id}: {str(e)}'
                                )
                            cot_details = {}
                        sql = current_sql_options.get('sql_query', '')
                        results = execution_details.get('result_rows', [])
                        explanation = cot_details.get('explanation', '')
                        answer_text = format_answer_from_results(results)
                        answers.append({'query_id': query_id, 'question':
                            query_record['NL_question'], 'answer':
                            answer_text, 'results': results})
                        queries.append({'query_id': query_id, 'sql': sql,
                            'explanation': explanation})
                    else:
                        question = query_record['NL_question']
                        result = generate_and_execute_sql(conn, query_id,
                            question, schema_data, clean_schema_data,
                            compact_stats_data, prompts)
                        if result:
                            answers.append(result['answer'])
                            queries.append(result['query'])
                else:
                    logger.info(f'Processing new suggestion: {question}')
                    pillar = suggestion.get('pillar', 'Refinement Question')
                    component = suggestion.get('component', 'General')
                    purpose = suggestion.get('purpose', '')
                    rationale = suggestion.get('rationale', '')
                    framework_details = {'pillar': pillar, 'component':
                        component, 'purpose': purpose, 'rationale':
                        rationale, 'type': 'refinement_question'}
                    if 'Cognitive Vulnerability' in pillar:
                        framework_factor = 'Bias Mitigation'
                    elif 'Dataset Schema' in pillar:
                        framework_factor = 'Data Structure Validation'
                    elif 'Toulmin Argument' in pillar:
                        framework_factor = 'Argument Enhancement'
                    elif 'Counter-Argument' in pillar:
                        framework_factor = 'Counter-Argument Testing'
                    else:
                        framework_factor = 'Refinement Question'
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        SELECT MAX(model_query_sequence_index) as max_idx
                        FROM query
                        WHERE dataset_id = %s AND query_model = 'baqr'
                    """
                        , (dataset_id,))
                    result = cursor.fetchone()
                    max_idx = result[0] if result[0] else 0
                    sequence_index = max_idx + 1
                    insert_query = """
                    INSERT INTO query 
                    (dataset_id, query_model, NL_question, model_query_sequence_index, 
                    framework_details, framework_contribution_factor_name, sql_generation_status, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    cursor.execute(insert_query, (dataset_id, 'baqr',
                        question, sequence_index, json.dumps(
                        framework_details), framework_factor, 'pending',
                        'active'))
                    query_id = cursor.lastrowid
                    cursor.close()
                    conn.commit()
                    logger.info(f'Created new query record with ID {query_id}')
                    result = generate_and_execute_sql(conn, query_id,
                        question, schema_data, clean_schema_data,
                        compact_stats_data, prompts)
                    if result:
                        answers.append(result['answer'])
                        queries.append(result['query'])
            except Exception as e:
                logger.error(f'Error processing suggestion: {str(e)}')
                logger.error(traceback.format_exc())
                continue
        conn.close()
        reasoning = (
            'Results for selected refinement queries. Each query provides additional insights related to your question and decision context.'
            )
        return jsonify({'success': True, 'answers': answers, 'queries':
            queries, 'reasoning': reasoning})
    except Exception as e:
        logger.error(f'Error in process_selected_suggestions: {str(e)}')
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


def generate_and_execute_sql(conn, query_id, question, schema_data,
    clean_schema_data, compact_stats_data, prompts):
    try:
        sql, thought_process, explanation = generate_sql_with_flash(question,
            schema_data, clean_schema_data, compact_stats_data, prompts)
        if not sql:
            update_query_with_execution_results(conn, query_id, '', 
                thought_process or '', explanation or '', {'success': False,
                'error': 'Failed to generate SQL query'}, 'a1_done')
            return {'answer': {'query_id': query_id, 'question': question,
                'error':
                'Sorry, we could not generate a SQL query for this question'
                }, 'query': {'query_id': query_id, 'error':
                'Failed to generate SQL query'}}
        execution_result = execute_sql_query(sql)
        if execution_result.get('success'):
            update_query_with_execution_results(conn, query_id, sql,
                thought_process, explanation, execution_result, 'a1_done')
            results = execution_result.get('result_rows', [])
            answer_text = format_answer_from_results(results)
            return {'answer': {'query_id': query_id, 'question': question,
                'answer': answer_text, 'results': results}, 'query': {
                'query_id': query_id, 'sql': sql, 'explanation': explanation}}
        logger.info(
            f"First SQL execution failed. Error: {execution_result.get('error')}. Attempting retry."
            )
        update_query_with_execution_results(conn, query_id, sql,
            thought_process, explanation, execution_result, 'a1_done')
        error_info = {'previous_sql': sql, 'error': execution_result.get(
            'error', ''), 'traceback': execution_result.get('traceback', '')}
        sql, thought_process, explanation = generate_sql_with_flash(question,
            schema_data, clean_schema_data, compact_stats_data, prompts,
            is_retry=True, error_info=error_info)
        if not sql:
            update_query_with_execution_results(conn, query_id, '', 
                thought_process or '', explanation or '', {'success': False,
                'error': 'Failed to generate valid SQL on retry'}, 'a2_done')
            return {'answer': {'query_id': query_id, 'question': question,
                'error':
                'Sorry, we could not execute this query against the available dataset'
                }, 'query': {'query_id': query_id, 'error':
                'The query could not be executed with the current dataset schema'
                }}
        execution_result = execute_sql_query(sql)
        update_query_with_execution_results(conn, query_id, sql,
            thought_process, explanation, execution_result, 'a2_done')
        if execution_result.get('success'):
            results = execution_result.get('result_rows', [])
            answer_text = format_answer_from_results(results)
            return {'answer': {'query_id': query_id, 'question': question,
                'answer': answer_text, 'results': results}, 'query': {
                'query_id': query_id, 'sql': sql, 'explanation': explanation}}
        else:
            return {'answer': {'query_id': query_id, 'question': question,
                'error':
                'Sorry, we could not execute this query against the available dataset'
                }, 'query': {'query_id': query_id, 'sql': sql, 'error':
                'The query could not be executed with the current dataset schema'
                }}
    except Exception as e:
        logger.error(f'Error generating and executing SQL: {str(e)}')
        logger.error(traceback.format_exc())
        return None
