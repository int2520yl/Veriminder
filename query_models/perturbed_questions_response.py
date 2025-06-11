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
os.makedirs('logs', exist_ok=True)
logging.basicConfig(filename='logs/perturbed_questions_response.log', level
    =logging.INFO, format=
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
            "SELECT COUNT(*) as count FROM dataset WHERE perturbed_question_set_to_sql_status = 'processing'"
            )
        result = cursor.fetchone()
        if result['count'] > 0:
            logging.error(
                "Found records with 'processing' status. Please check for failures in previous runs."
                )
            raise Exception("Records with 'processing' status found. Exiting.")
        cursor.execute(
            "SELECT id, question_id_from_BIRD, question FROM dataset WHERE perturbed_question_set_to_sql_status = 'ready' LIMIT %s"
            , (limit,))
        records = cursor.fetchall()
        if records:
            ids = [record['id'] for record in records]
            placeholders = ', '.join(['%s'] * len(ids))
            cursor.execute(
                f"UPDATE dataset SET perturbed_question_set_to_sql_status = 'processing' WHERE id IN ({placeholders})"
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
    questions = []
    for record in records:
        question_data = json.loads(record['question'])
        question_text = question_data.get('text', '')
        questions.append({'dataset_id': record['id'], 'bird_id': record[
            'question_id_from_BIRD'], 'question': question_text})
    prompt = f"""
You are a data analytics expert who helps explore data from multiple perspectives.

For each question, create ONLY meaningful perturbed versions that offer alternative analytical angles. These questions should reveal different insights that would help with data-driven decisions.

{json.dumps(questions, indent=2)}

{json.dumps(schema_data, indent=2)}

{json.dumps(all_relevant_evidence, indent=2)}

1. ALL perturbed questions MUST be translatable to SQL queries using the provided database schema
2. Questions should reference specific database tables and columns
3. Questions should be clear, specific, and well-formed
4. Only include perturbed questions that provide meaningful insights by varying specific core elements of the original question

Return a JSON array with one object per question, containing:
- dataset_id: The ID from the original question
- bird_id: The Bird ID from the original question
- original_question: The original question text
- perturbed_questions: Array of objects with "question_text", "perturbation_rationale", and "framework" fields

The "framework" field should indicate which analytical framework the question addresses (e.g., "Temporal Analysis", "Demographic Comparison", "Regional Variation").

IMPORTANT: Ensure your response is valid JSON format.
"""
    return prompt


def get_flash_response_schema():
    response_schema = {'type': 'ARRAY', 'items': {'type': 'OBJECT',
        'properties': {'dataset_id': {'type': 'INTEGER'}, 'bird_id': {
        'type': 'INTEGER'}, 'original_question': {'type': 'STRING'},
        'perturbed_questions': {'type': 'ARRAY', 'items': {'type': 'OBJECT',
        'properties': {'question_text': {'type': 'STRING'},
        'perturbation_rationale': {'type': 'STRING'}, 'framework': {'type':
        'STRING'}}, 'required': ['question_text', 'perturbation_rationale',
        'framework']}}}, 'required': ['dataset_id', 'original_question',
        'perturbed_questions']}}
    return response_schema


def query_claude(prompt):
    try:
        logging.info('Sending batch request to Claude API using streaming')
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        prompt_file = f'logs/claude_prompt_{timestamp}.txt'
        with open(prompt_file, 'w', encoding='utf-8') as f:
            f.write(prompt)
        logging.info(f'Full prompt saved to {prompt_file}')
        logging.info(f'PROMPT (truncated):\n{prompt[:1000]}...')
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
            return json.loads(response_text)
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


def insert_original_question(conn, dataset_id, original_question):
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO query 
            (dataset_id, query_model, NL_question, model_query_sequence_index, 
             framework_details, framework_contribution_factor_name, sql_generation_status, execution_status, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            , (dataset_id, 'perturbed_question_set_to_sql',
            original_question, 1, json.dumps({'type': 'Original Question'}),
            'Original Question', 'pending', 'pending', 'active'))
        conn.commit()
        cursor.close()
        logging.info(
            f'Successfully inserted original question for dataset_id {dataset_id}'
            )
        return True
    except Exception as e:
        logging.error(f'Error inserting original question: {str(e)}')
        return False


def insert_perturbed_questions(conn, dataset_id, perturbed_questions):
    try:
        cursor = conn.cursor()
        sequence_index = 2
        success_count = 0
        for perturbed in perturbed_questions:
            question_text = perturbed.get('question_text', '')
            perturbation_rationale = perturbed.get('perturbation_rationale', ''
                )
            framework = perturbed.get('framework', 'General Analysis')
            framework_details = {'perturbation_rationale':
                perturbation_rationale}
            cursor.execute(
                """
                INSERT INTO query 
                (dataset_id, query_model, NL_question, model_query_sequence_index, 
                 framework_details, framework_contribution_factor_name, sql_generation_status, execution_status, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                , (dataset_id, 'perturbed_question_set_to_sql',
                question_text, sequence_index, json.dumps(framework_details
                ), framework, 'pending', 'pending', 'active'))
            sequence_index += 1
            success_count += 1
        conn.commit()
        cursor.close()
        logging.info(
            f'Successfully inserted {success_count} perturbed questions for dataset_id {dataset_id}'
            )
        return success_count
    except Exception as e:
        logging.error(f'Error inserting perturbed questions: {str(e)}')
        return 0


def process_batch_response(conn, records, responses):
    question_lookup = {}
    for record in records:
        question_data = json.loads(record['question'])
        question_lookup[record['id']] = {'text': question_data.get('text',
            ''), 'bird_id': record['question_id_from_BIRD']}
    if not responses:
        logging.error('No responses to process')
        return
    logging.info(f'Processing {len(responses)} responses')
    for response in responses:
        if not isinstance(response, dict):
            logging.error(
                f'Invalid response object (not a dict): {type(response)}')
            continue
        dataset_id = response.get('dataset_id')
        if dataset_id is None:
            logging.error(f'Missing dataset_id in response: {response}')
            continue
        if dataset_id not in question_lookup:
            logging.error(f'Dataset ID {dataset_id} not found in current batch'
                )
            continue
        try:
            original_question = response.get('original_question',
                question_lookup[dataset_id]['text'])
            original_success = insert_original_question(conn, dataset_id,
                original_question)
            perturbed_questions = response.get('perturbed_questions', [])
            perturbed_success_count = 0
            if original_success and perturbed_questions:
                perturbed_success_count = insert_perturbed_questions(conn,
                    dataset_id, perturbed_questions)
            if original_success and perturbed_success_count > 0:
                update_record_status(conn, dataset_id, 'success')
            else:
                handle_record_failure(conn, dataset_id)
        except Exception as e:
            logging.error(
                f'Error processing response for dataset_id {dataset_id}: {str(e)}'
                )
            logging.error(traceback.format_exc())
            handle_record_failure(conn, dataset_id)


def update_record_status(conn, dataset_id, status):
    try:
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE dataset SET perturbed_question_set_to_sql_status = %s WHERE id = %s'
            , (status, dataset_id))
        conn.commit()
        cursor.close()
        logging.info(f"Updated dataset_id {dataset_id} status to '{status}'")
    except Exception as e:
        logging.error(f'Error updating record status: {str(e)}')


def handle_record_failure(conn, dataset_id):
    update_record_status(conn, dataset_id, 'failed')


def handle_failed_batch(conn, records):
    try:
        cursor = conn.cursor()
        ids = [record['id'] for record in records]
        placeholders = ', '.join(['%s'] * len(ids))
        cursor.execute(
            f"UPDATE dataset SET perturbed_question_set_to_sql_status = 'failed' WHERE id IN ({placeholders})"
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
    logging.info(
        f'Starting perturbed_questions_response.py script with {LLM_MODEL} model'
        )
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
            else:
                process_batch_response(conn, records, responses)
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
        logging.info(f'Total records processed: {total_processed}')
    except Exception as e:
        logging.error(f'Script failed with error: {str(e)}')
        logging.error(traceback.format_exc())


if __name__ == '__main__':
    main()
