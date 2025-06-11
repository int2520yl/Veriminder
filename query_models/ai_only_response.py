import json
import os
import anthropic
import mysql.connector
from mysql.connector import Error
import logging
import time
from datetime import datetime
import traceback
from google import genai
from google.genai import types
import logging.handlers
os.makedirs('logs', exist_ok=True)
log_handler = logging.handlers.RotatingFileHandler('logs/ai_only_response.log',
    maxBytes=10485760, backupCount=5)
logging.basicConfig(handlers=[log_handler], level=logging.INFO, format=
    '%(asctime)s - %(levelname)s - %(pathname)s:%(lineno)d - %(message)s')
DB_CONFIG = {
    'host': 'YOUR_DATABASE_HOST',
    'port': 'YOUR_DATABASE_POST',
    'user': 'YOUR_DATABASE_USER',
    'password': 'YOUR_DATABASE_PASSWORD',
    'database': 'YOUR_DATABASE_NAME'
}

LLM_MODEL = 'FLASH'
CLAUDE_API_KEY = (
    'ENTER_KEY'
    )
CLAUDE_CLIENT = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
FLASH_CLIENT = genai.Client(project="your-gcp-project-id")
FLASH_MODEL = 'gemini-2.0-flash-001'
EVIDENCE_FILE_PATH = '../data/all_evidence.json'
SCHEMA_FILE_PATH = '../data/BIRD_table_schema_info.json'
TEST_MODE = False
BATCH_SIZE = 3


def load_files():
    try:
        with open(EVIDENCE_FILE_PATH, 'r') as f:
            evidence_data = json.load(f)
        with open(SCHEMA_FILE_PATH, 'r') as f:
            schema_data = json.load(f)
        return evidence_data, schema_data
    except Exception as e:
        logging.error(f'Error loading files: {str(e)}')
        raise


def get_db_connection():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except Error as e:
        logging.error(f'Database connection error: {str(e)}')
        raise


def get_dataset_records(conn, limit=10):
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT COUNT(*) as count FROM dataset WHERE ai_only_response_status = 'processing'"
            )
        result = cursor.fetchone()
        if result['count'] > 0:
            logging.error(
                "Found records with 'processing' status. Please check for failures in previous runs."
                )
            raise Exception("Records with 'processing' status found. Exiting.")
        cursor.execute(
            "SELECT id, question_id_from_BIRD, decision FROM dataset WHERE ai_only_response_status = 'ready' LIMIT %s"
            , (limit,))
        records = cursor.fetchall()
        if records:
            ids = [record['id'] for record in records]
            placeholders = ', '.join(['%s'] * len(ids))
            cursor.execute(
                f"UPDATE dataset SET ai_only_response_status = 'processing' WHERE id IN ({placeholders})"
                , ids)
            conn.commit()
        cursor.close()
        return records
    except Exception as e:
        logging.error(f'Error getting dataset records: {str(e)}')
        raise


def prepare_batch_prompt(records, evidence_data, schema_data):
    bird_ids = [record['question_id_from_BIRD'] for record in records]
    all_relevant_evidence = []
    for evidence_obj in evidence_data:
        for evidence_text, question_ids in evidence_obj.items():
            if any(str(bird_id) in question_ids for bird_id in bird_ids):
                if evidence_text not in all_relevant_evidence:
                    all_relevant_evidence.append(evidence_text)
    decisions = []
    for record in records:
        decision_data = json.loads(record['decision'])
        decision_text = decision_data.get('text', '')
        decisions.append({'dataset_id': record['id'], 'bird_id': record[
            'question_id_from_BIRD'], 'decision': decision_text})
    prompt = f"""
You are a data analytics expert who helps users formulate data questions to support their decisions.

For each decision provided, generate questions that would help gather data insights to inform the decision-making process.

{json.dumps(decisions, indent=2)}

{json.dumps(schema_data, indent=2)}

{json.dumps(all_relevant_evidence, indent=2)}

1. ALL questions MUST be translatable to SQL queries using the provided database schema
2. Questions should reference specific database tables and columns when appropriate
3. Questions should be clear, specific, and directly relevant to the decision

Return a JSON array with one object per decision, containing:
- dataset_id: The ID from the decision
- bird_id: The Bird ID from the decision
- thought_process: Brief analysis of the decision context and data needs
- questions: Array of objects with "question" and "rationale" fields

IMPORTANT: Ensure your response is valid JSON format.
"""
    return prompt


def get_flash_response_schema():
    response_schema = {'type': 'ARRAY', 'items': {'type': 'OBJECT',
        'properties': {'dataset_id': {'type': 'INTEGER'}, 'bird_id': {
        'type': 'INTEGER'}, 'thought_process': {'type': 'STRING'},
        'questions': {'type': 'ARRAY', 'items': {'type': 'OBJECT',
        'properties': {'question': {'type': 'STRING'}, 'rationale': {'type':
        'STRING'}}, 'required': ['question', 'rationale']}}}, 'required': [
        'dataset_id', 'bird_id', 'thought_process', 'questions']}}
    return response_schema


def query_claude(prompt):
    try:
        logging.info('Sending batch request to Claude API using streaming')
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        prompt_file = f'logs/claude_prompt_{timestamp}.txt'
        with open(prompt_file, 'w', encoding='utf-8') as f:
            f.write(prompt)
        logging.info(f'Full prompt saved to {prompt_file}')
        logging.info(f'PROMPT (truncated):\n{prompt[:2000]}...')
        response_text = ''
        thinking_text = ''
        with CLAUDE_CLIENT.beta.messages.stream(model=
            'claude-3-7-sonnet-20250219', max_tokens=128000, thinking={
            'type': 'enabled', 'budget_tokens': 2000}, messages=[{'role':
            'user', 'content': prompt}], betas=['output-128k-2025-02-19']
            ) as stream:
            for event in stream:
                if event.type == 'content_block_delta':
                    if event.delta.type == 'thinking_delta':
                        thinking_text += event.delta.thinking
                    elif event.delta.type == 'text_delta':
                        response_text += event.delta.text
                elif event.type == 'content_block_stop':
                    logging.info('Content block complete')
        response_file = f'logs/claude_response_{timestamp}.txt'
        thinking_file = f'logs/claude_thinking_{timestamp}.txt'
        with open(response_file, 'w', encoding='utf-8') as f:
            f.write(response_text)
        with open(thinking_file, 'w', encoding='utf-8') as f:
            f.write(thinking_text)
        logging.info(f'Full response saved to {response_file}')
        logging.info(f'Full thinking saved to {thinking_file}')
        try:
            json_start = response_text.find('```json')
            if json_start >= 0:
                json_start += 7
                json_end = response_text.find('```', json_start)
                if json_end > json_start:
                    json_str = response_text[json_start:json_end].strip()
                    return json.loads(json_str)
            json_start = response_text.find('```')
            if json_start >= 0:
                json_start += 3
                json_end = response_text.find('```', json_start)
                if json_end > json_start:
                    json_str = response_text[json_start:json_end].strip()
                    return json.loads(json_str)
            array_start = response_text.find('[')
            if array_start >= 0:
                array_end = response_text.rfind(']') + 1
                if array_end > array_start:
                    json_str = response_text[array_start:array_end]
                    return json.loads(json_str)
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            logging.error(f'Error parsing JSON: {str(e)}')
            logging.error(
                f"Failed JSON string: {json_str if 'json_str' in locals() else 'Not identified'}"
                )
            return []
    except Exception as e:
        logging.error(f'Error calling Claude API: {str(e)}')
        logging.error(traceback.format_exc())
        return []


def query_flash(content_prompt):
    try:
        logging.info(
            'Sending batch request to Flash (Gemini) API using streaming')
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        prompt_file = f'logs/flash_prompt_{timestamp}.txt'
        with open(prompt_file, 'w', encoding='utf-8') as f:
            f.write(content_prompt)
        logging.info(f'Full prompt saved to {prompt_file}')
        response_schema = get_flash_response_schema()
        generate_content_config = types.GenerateContentConfig(temperature=0,
            top_p=0.95, max_output_tokens=8192, response_modalities=['TEXT'
            ], safety_settings=[types.SafetySetting(category=
            'HARM_CATEGORY_HATE_SPEECH', threshold='OFF'), types.
            SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT',
            threshold='OFF'), types.SafetySetting(category=
            'HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='OFF'), types.
            SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold=
            'OFF')], response_mime_type='application/json', response_schema
            =response_schema)
        contents = [types.Content(role='user', parts=[types.Part.from_text(
            text=content_prompt)])]
        response_text = ''
        for chunk in FLASH_CLIENT.models.generate_content_stream(model=
            FLASH_MODEL, contents=contents, config=generate_content_config):
            chunk_text = chunk.text if chunk.text else ''
            response_text += chunk_text
        response_file = f'logs/flash_response_{timestamp}.txt'
        with open(response_file, 'w', encoding='utf-8') as f:
            f.write(response_text)
        logging.info(f'Full response saved to {response_file}')
        try:
            parsed_response = json.loads(response_text)
            logging.info('Successfully parsed JSON directly')
            return parsed_response
        except json.JSONDecodeError as e:
            logging.warning(f'Direct JSON parsing failed: {str(e)}')
            if not response_text.strip().endswith(']'):
                logging.warning(
                    'Response appears to be truncated - attempting recovery')
                last_object_end = response_text.rfind('},')
                if last_object_end > 0:
                    fixed_json = response_text[:last_object_end + 1] + ']'
                    try:
                        return json.loads(fixed_json)
                    except json.JSONDecodeError as e2:
                        logging.error(f'Recovery attempt failed: {str(e2)}')
            logging.error('All JSON parsing attempts failed')
            return []
    except Exception as e:
        logging.error(f'Error calling Flash API: {str(e)}')
        logging.error(traceback.format_exc())
        return []


def insert_question_results(conn, dataset_id, response_data, questions):
    try:
        cursor = conn.cursor()
        for idx, question_data in enumerate(questions, start=1):
            nl_question = question_data.get('question', '')
            if not nl_question:
                logging.warning(
                    f'Empty question text found for dataset_id {dataset_id}, index {idx}'
                    )
                continue
            framework_details = {'rationale': question_data.get('rationale',
                ''), 'thought_process': response_data.get('thought_process',
                '')}
            cursor.execute(
                """
                INSERT INTO query 
                (dataset_id, query_model, NL_question, model_query_sequence_index, 
                framework_details, framework_contribution_factor_name, sql_generation_status, execution_status, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                , (dataset_id, 'ai_only_response', nl_question, idx, json.
                dumps(framework_details), 'Decision Support', 'pending',
                'pending', 'active'))
        cursor.execute(
            'UPDATE dataset SET ai_only_response_status = %s WHERE id = %s',
            ('success', dataset_id))
        conn.commit()
        cursor.close()
        logging.info(
            f'Successfully inserted {len(questions)} questions for dataset_id {dataset_id}'
            )
        return True
    except Exception as e:
        logging.error(f'Error inserting question results: {str(e)}')
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE dataset SET ai_only_response_status = 'failed' WHERE id = %s"
                , (dataset_id,))
            conn.commit()
            cursor.close()
        except Exception as inner_e:
            logging.error(
                f"Failed to update dataset status to 'failed' for dataset_id {dataset_id}: {str(inner_e)}"
                )
        return False


def process_batch_response(conn, records, responses):
    success_count = 0
    failure_count = 0
    dataset_map = {record['id']: record for record in records}
    for response in responses:
        dataset_id = response.get('dataset_id')
        if dataset_id is None:
            logging.error(f'Invalid dataset_id in response: {response}')
            continue
        if dataset_id not in dataset_map:
            logging.error(f'Dataset ID {dataset_id} not found in current batch'
                )
            continue
        try:
            questions = response.get('questions', [])
            if not questions:
                logging.warning(
                    f'No questions provided for dataset_id {dataset_id}')
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE dataset SET ai_only_response_status = 'failed' WHERE id = %s"
                    , (dataset_id,))
                conn.commit()
                cursor.close()
                failure_count += 1
                continue
            if insert_question_results(conn, dataset_id, response, questions):
                success_count += 1
            else:
                failure_count += 1
        except Exception as e:
            logging.error(
                f'Error processing response for dataset_id {dataset_id}: {str(e)}'
                )
            logging.error(traceback.format_exc())
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE dataset SET ai_only_response_status = 'failed' WHERE id = %s"
                    , (dataset_id,))
                conn.commit()
                cursor.close()
            except Exception as inner_e:
                logging.error(
                    f"Failed to update dataset status to 'failed' for dataset_id {dataset_id}: {str(inner_e)}"
                    )
            failure_count += 1
    return success_count, failure_count


def handle_failed_batch(conn, records):
    try:
        cursor = conn.cursor()
        ids = [record['id'] for record in records]
        placeholders = ', '.join(['%s'] * len(ids))
        cursor.execute(
            f"UPDATE dataset SET ai_only_response_status = 'failed' WHERE id IN ({placeholders})"
            , ids)
        conn.commit()
        cursor.close()
        logging.info(
            f'Marked {len(ids)} records as failed due to batch processing failure'
            )
    except Exception as e:
        logging.error(f'Error marking records as failed: {str(e)}')


def main():
    start_time = time.time()
    total_processed = 0
    total_success = 0
    total_failure = 0
    logging.info(f'Starting ai_only_response.py script with {LLM_MODEL} model')
    try:
        evidence_data, schema_data = load_files()
        logging.info('Successfully loaded evidence and schema files')
        conn = get_db_connection()
        logging.info('Successfully connected to the database')
        batch_count = 0
        while True:
            batch_count += 1
            batch_start_time = time.time()
            batch_size = 1 if TEST_MODE else BATCH_SIZE
            records = get_dataset_records(conn, batch_size)
            logging.info(
                f'Batch {batch_count}: Found {len(records)} records to process'
                )
            if not records:
                logging.info('No more records to process. Exiting.')
                break
            logging.info(
                f'Processing batch {batch_count} with {len(records)} records')
            prompt = prepare_batch_prompt(records, evidence_data, schema_data)
            if LLM_MODEL == 'CLAUDE':
                responses = query_claude(prompt)
                logging.info('Used Claude for batch processing')
            else:
                responses = query_flash(prompt)
                logging.info('Used Flash for batch processing')
            if not responses:
                logging.error(
                    f'Batch {batch_count}: No valid responses received from {LLM_MODEL}'
                    )
                handle_failed_batch(conn, records)
                total_failure += len(records)
            else:
                success_count, failure_count = process_batch_response(conn,
                    records, responses)
                total_success += success_count
                total_failure += failure_count
            total_processed += len(records)
            batch_elapsed_time = time.time() - batch_start_time
            logging.info(
                f'Batch {batch_count} completed in {batch_elapsed_time:.2f} seconds'
                )
            if TEST_MODE:
                logging.info(
                    'Test mode enabled. Exiting after processing one batch.')
                break
        conn.close()
        elapsed_time = time.time() - start_time
        logging.info(
            f'Script completed successfully in {elapsed_time:.2f} seconds')
        logging.info(
            f'Total records processed: {total_processed}, Success: {total_success}, Failure: {total_failure}'
            )
    except Exception as e:
        logging.error(f'Script failed with error: {str(e)}')
        logging.error(traceback.format_exc())


if __name__ == '__main__':
    main()
