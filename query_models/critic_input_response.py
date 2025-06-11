import json
import os
import anthropic
import mysql.connector
from mysql.connector import Error
import logging
import time
from datetime import datetime
import traceback
from logging.handlers import RotatingFileHandler
from google import genai
from google.genai import types
log_dir = 'logs'
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'critic_input_response.log')
handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024,
    backupCount=5)
logging.basicConfig(handlers=[handler], level=logging.INFO, format=
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
            "SELECT COUNT(*) as count FROM dataset WHERE with_critic_agent_input_status = 'processing'"
            )
        result = cursor.fetchone()
        if result['count'] > 0:
            logging.error(
                "Found records with 'processing' status. Please check for failures in previous runs."
                )
            raise Exception("Records with 'processing' status found. Exiting.")
        cursor.execute(
            "SELECT id, question_id_from_BIRD, question, decision FROM dataset WHERE with_critic_agent_input_status = 'ready' LIMIT %s"
            , (limit,))
        records = cursor.fetchall()
        if records:
            ids = [record['id'] for record in records]
            placeholders = ', '.join(['%s'] * len(ids))
            cursor.execute(
                f"UPDATE dataset SET with_critic_agent_input_status = 'processing' WHERE id IN ({placeholders})"
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
    dataset_entries = []
    for record in records:
        question_data = json.loads(record['question'])
        decision_data = json.loads(record['decision'])
        question_text = question_data.get('text', '')
        decision_text = decision_data.get('text', '')
        dataset_entries.append({'dataset_id': record['id'], 'bird_id':
            record['question_id_from_BIRD'], 'question': question_text,
            'decision': decision_text})
    prompt = f"""
You are an expert system with two specialized roles: a Critic Agent and a Data Analyst Agent.

For each dataset entry:
1. As the Critic Agent, analyze the original question in the context of the decision
2. As the Data Analyst Agent, create better questions based on the critique
3. Generate SQL-compatible questions that will improve decision-making

{json.dumps(dataset_entries, indent=2)}

{json.dumps(schema_data, indent=2)}

{json.dumps(all_relevant_evidence, indent=2)}

1. All questions MUST be translatable to SQL queries using the provided database schema
2. Questions should reference specific database tables and columns
3. Questions should be clear, specific, and well-formed

Return a JSON array with one object per dataset entry, containing:
- dataset_id: The ID from the dataset entry
- bird_id: The Bird ID from the dataset entry
- original_question: The original question from the dataset entry
- critic_assessment: Object with "summary" field that summarizes the critique
- data_analyst_response: Object with "revised_questions" array containing objects with "question_text", "pillar", and "rationale" fields

The "pillar" field should indicate which aspect the question addresses (Decision Relevance, Analytical Completeness, Cognitive Vulnerability, or Methodological Soundness).

IMPORTANT: Ensure your response is valid JSON format.
"""
    return prompt


def get_flash_response_schema():
    response_schema = {'type': 'ARRAY', 'items': {'type': 'OBJECT',
        'properties': {'dataset_id': {'type': 'INTEGER'}, 'bird_id': {
        'type': 'INTEGER'}, 'original_question': {'type': 'STRING'},
        'critic_assessment': {'type': 'OBJECT', 'properties': {'summary': {
        'type': 'STRING'}}, 'required': ['summary']},
        'data_analyst_response': {'type': 'OBJECT', 'properties': {
        'revised_questions': {'type': 'ARRAY', 'items': {'type': 'OBJECT',
        'properties': {'question_text': {'type': 'STRING'}, 'pillar': {
        'type': 'STRING'}, 'rationale': {'type': 'STRING'}}, 'required': [
        'question_text', 'pillar', 'rationale']}}}, 'required': [
        'revised_questions']}}, 'required': ['dataset_id', 'bird_id',
        'original_question', 'critic_assessment', 'data_analyst_response']}}
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


def insert_original_question(conn, dataset_id, original_question_text):
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO query 
            (dataset_id, query_model, NL_question, model_query_sequence_index, 
            framework_details, framework_contribution_factor_name, sql_generation_status, execution_status, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            , (dataset_id, 'with_critic_agent_input',
            original_question_text, 1, json.dumps({'type':
            'original_question'}), 'Original Question', 'pending',
            'pending', 'active'))
        conn.commit()
        cursor.close()
        logging.info(
            f'Successfully inserted original question for dataset_id {dataset_id}'
            )
        return True
    except Exception as e:
        logging.error(f'Error inserting original question: {str(e)}')
        return False


def insert_revised_questions(conn, dataset_id, critic_assessment,
    data_analyst_response):
    try:
        cursor = conn.cursor()
        sequence_index = 2
        success_count = 0
        critic_summary = critic_assessment.get('summary', '')
        revised_questions = data_analyst_response.get('revised_questions', [])
        for revised in revised_questions:
            question_text = revised.get('question_text', '')
            pillar = revised.get('pillar', '')
            rationale = revised.get('rationale', '')
            framework_details = {'critic_assessment': critic_assessment,
                'rationale': rationale}
            cursor.execute(
                """
                INSERT INTO query 
                (dataset_id, query_model, NL_question, model_query_sequence_index, 
                framework_details, framework_contribution_factor_name, sql_generation_status, execution_status, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                , (dataset_id, 'with_critic_agent_input', question_text,
                sequence_index, json.dumps(framework_details), pillar,
                'pending', 'pending', 'active'))
            sequence_index += 1
            success_count += 1
        conn.commit()
        cursor.close()
        logging.info(
            f'Successfully inserted {success_count} revised questions for dataset_id {dataset_id}'
            )
        return success_count
    except Exception as e:
        logging.error(f'Error inserting revised questions: {str(e)}')
        return 0


def process_batch_response(conn, records, responses):
    data_lookup = {}
    for record in records:
        question_data = json.loads(record['question'])
        decision_data = json.loads(record['decision'])
        data_lookup[record['id']] = {'question_text': question_data.get(
            'text', ''), 'decision_text': decision_data.get('text', ''),
            'bird_id': record['question_id_from_BIRD']}
    if not responses:
        logging.error('No responses to process')
        return
    logging.info(f'Processing {len(responses)} responses')
    for response in responses:
        try:
            dataset_id = response.get('dataset_id')
            if dataset_id is None:
                logging.error('Invalid response: missing dataset_id')
                continue
            if dataset_id not in data_lookup:
                logging.error(f'Invalid dataset_id in response: {dataset_id}')
                continue
            original_question_text = response.get('original_question', '')
            if not original_question_text:
                logging.warning(
                    f'No valid original question for dataset_id {dataset_id}')
                handle_record_failure(conn, dataset_id)
                continue
            original_success = insert_original_question(conn, dataset_id,
                original_question_text)
            critic_assessment = response.get('critic_assessment', {})
            data_analyst_response = response.get('data_analyst_response', {})
            revised_success_count = 0
            if (original_success and data_analyst_response and 
                'revised_questions' in data_analyst_response):
                revised_success_count = insert_revised_questions(conn,
                    dataset_id, critic_assessment, data_analyst_response)
            if original_success and revised_success_count > 0:
                update_record_status(conn, dataset_id, 'success')
            else:
                handle_record_failure(conn, dataset_id)
        except Exception as e:
            logging.error(f'Error processing response item: {str(e)}')
            logging.error(traceback.format_exc())
            try:
                dataset_id = response.get('dataset_id')
                if dataset_id and dataset_id in data_lookup:
                    handle_record_failure(conn, dataset_id)
            except:
                pass


def update_record_status(conn, dataset_id, status):
    try:
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE dataset SET with_critic_agent_input_status = %s WHERE id = %s'
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
            f"UPDATE dataset SET with_critic_agent_input_status = 'failed' WHERE id IN ({placeholders})"
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
        f'Starting critic_input_response.py script with {LLM_MODEL} model')
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
