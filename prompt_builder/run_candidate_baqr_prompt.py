import json
import os
import logging
import random
import mysql.connector
from mysql.connector import Error
import time
from datetime import datetime
import traceback
from google import genai
from google.genai import types
os.makedirs('logs', exist_ok=True)
logging.basicConfig(filename='logs/run_candidate_baqr_prompt.log', level=
    logging.INFO, format=
    '%(asctime)s - %(levelname)s - %(pathname)s:%(lineno)d - %(message)s')
DB_CONFIG = {
    'host': 'YOUR_DATABASE_HOST',
    'port': 'YOUR_DATABASE_POST',
    'user': 'YOUR_DATABASE_USER',
    'password': 'YOUR_DATABASE_PASSWORD',
    'database': 'YOUR_DATABASE_NAME'
}

FLASH_CLIENT = genai.Client(project="your-gcp-project-id")
FLASH_MODEL = 'gemini-2.0-flash-001'
EVIDENCE_FILE_PATH = '../data/all_evidence.json'
SCHEMA_FILE_PATH = '../data/BIRD_table_schema_info.json'
STATS_FILE_PATH = '../data/compact_dataset_stats.json'
PILLAR_DIR = '../resources/question_guide_pillars/'
TOULMIN_FILE_PATH = os.path.join(PILLAR_DIR, 'toulmin_argument_structure.json')
DATASET_SCHEMA_FILE_PATH = os.path.join(PILLAR_DIR,
    'dataset_schema_based_patterns.json')
VULNERABILITY_FILE_PATH = os.path.join(PILLAR_DIR,
    'vulnerability_semantic_frames.json')
COUNTERARGUMENT_FILE_PATH = os.path.join(PILLAR_DIR,
    'preemptive-counterargument_pattern.json')


def get_db_connection():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except Error as e:
        logging.error(f'Database connection error: {str(e)}')
        raise


def get_candidates():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM bird_question_linked_to_cluster WHERE quality_score_for_inclusion = 'BEST_MUST_INCLUDE' AND status='candidate'"
            )
        candidates = cursor.fetchall()
        cursor.close()
        conn.close()
        logging.info(f'Retrieved {len(candidates)} candidates')
        return candidates
    except Exception as e:
        logging.error(f'Error getting candidates: {str(e)}')
        raise


def get_prompt_templates():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM baqr_prompt_template WHERE status='active'")
        templates = cursor.fetchall()
        cursor.close()
        conn.close()
        logging.info(f'Retrieved {len(templates)} prompt templates')
        return templates
    except Exception as e:
        logging.error(f'Error getting prompt templates: {str(e)}')
        raise


def get_flash_response_schema():
    response_schema = {'type': 'OBJECT', 'properties': {'dataset_id': {
        'type': 'INTEGER'}, 'bird_id': {'type': 'INTEGER'},
        'original_question': {'type': 'STRING'}, 'decision_context': {
        'type': 'STRING'}, 'primary_question': {'type': 'OBJECT',
        'properties': {'question': {'type': 'STRING'}, 'explanation': {
        'type': 'STRING'}}, 'required': ['question', 'explanation']},
        'refinement_questions': {'type': 'ARRAY', 'items': {'type':
        'OBJECT', 'properties': {'question': {'type': 'STRING'},
        'bias_dimension': {'type': 'STRING'}, 'specific_bias': {'type':
        'STRING'}, 'data_elements': {'type': 'STRING'},
        'bias_mitigation_explanation': {'type': 'STRING'},
        'hard_to_vary_contribution': {'type': 'STRING'}}, 'required': [
        'question', 'bias_dimension', 'specific_bias', 'data_elements',
        'bias_mitigation_explanation', 'hard_to_vary_contribution']}}},
        'required': ['dataset_id', 'bird_id', 'primary_question',
        'refinement_questions']}
    return response_schema


def query_flash(content_prompt):
    try:
        logging.info('Sending request to Flash (Gemini) API using streaming')
        logging.info(f'CONTENT PROMPT (truncated): {content_prompt[:500]}...')
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
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        response_file = f'logs/flash_response_{timestamp}.txt'
        with open(response_file, 'w', encoding='utf-8') as f:
            f.write(response_text)
        logging.info(f'Full response saved to {response_file}')
        return response_text
    except Exception as e:
        logging.error(f'Error calling Flash API: {str(e)}')
        logging.error(traceback.format_exc())
        return ''


def prepare_prompt(prompt_template, candidate):
    try:
        detailed_prompt_json = prompt_template['detailed_prompt']
        if isinstance(detailed_prompt_json, str):
            detailed_prompt = json.loads(detailed_prompt_json)
        else:
            detailed_prompt = detailed_prompt_json
        prompt_text = ''
        if isinstance(detailed_prompt, dict):
            if 'text' in detailed_prompt:
                prompt_text = detailed_prompt['text']
            elif 'prompt' in detailed_prompt:
                prompt_text = detailed_prompt['prompt']
            elif 'content' in detailed_prompt:
                prompt_text = detailed_prompt['content']
            else:
                prompt_text = json.dumps(detailed_prompt, indent=2)
        elif isinstance(detailed_prompt, str):
            prompt_text = detailed_prompt
        else:
            prompt_text = json.dumps(detailed_prompt, indent=2)
        dataset_id = candidate['id']
        bird_id = candidate['bird_question_id']
        question_text = candidate['question_text'] or ''
        decision_text = candidate['decision_text'] or ''
        prompt_text = prompt_text.replace('{evidence_path}', EVIDENCE_FILE_PATH
            )
        prompt_text = prompt_text.replace('{schema_path}', SCHEMA_FILE_PATH)
        prompt_text = prompt_text.replace('{stats_path}', STATS_FILE_PATH)
        prompt_text = prompt_text.replace('{vulnerability_frames_path}',
            VULNERABILITY_FILE_PATH)
        prompt_text = prompt_text.replace('{dataset_schema_path}',
            DATASET_SCHEMA_FILE_PATH)
        prompt_text = prompt_text.replace('{toulmin_path}', TOULMIN_FILE_PATH)
        prompt_text = prompt_text.replace('{counterargument_path}',
            COUNTERARGUMENT_FILE_PATH)
        dataset_entry = {'dataset_id': dataset_id, 'bird_id': bird_id,
            'question': question_text, 'decision': decision_text}
        prompt_text += (
            f'\n\n```json\n{json.dumps(dataset_entry, indent=2)}\n```\n\n')
        prompt_text += f'# Original Question\n{question_text}\n\n'
        prompt_text += f'# Decision Context\n{decision_text}\n\n'
        prompt_text += (
            'Please analyze this decision scenario and generate appropriate questions following the framework above.'
            )
        return prompt_text
    except Exception as e:
        logging.error(f'Error preparing prompt: {str(e)}')
        logging.error(traceback.format_exc())
        raise


def store_response(baqr_prompt_template_id, candidate_id, response_text):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO baqr_prompt_template_nl_questions 
            (baqr_prompt_template_id, bird_question_linked_to_cluster_id, refinement_question_with_explanation_set, status)
            VALUES (%s, %s, %s, %s)
            """
            , (baqr_prompt_template_id, candidate_id, response_text,
            'pending_critic'))
        conn.commit()
        cursor.close()
        conn.close()
        logging.info(
            f'Stored response for prompt_template_id {baqr_prompt_template_id} and candidate_id {candidate_id}'
            )
        return True
    except Exception as e:
        logging.error(f'Error storing response: {str(e)}')
        return False


def main():
    start_time = time.time()
    logging.info('Starting run_candidate_baqr_prompt.py script')
    try:
        candidates = get_candidates()
        prompt_templates = get_prompt_templates()
        if len(candidates) < 12:
            logging.error(
                f'Expected at least 12 candidates, but found {len(candidates)}'
                )
            raise ValueError(
                f'Expected at least 12 candidates, but found {len(candidates)}'
                )
        if len(prompt_templates) < 12:
            logging.error(
                f'Expected at least 12 prompt templates, but found {len(prompt_templates)}'
                )
            raise ValueError(
                f'Expected at least 12 prompt templates, but found {len(prompt_templates)}'
                )
        candidates = candidates[:12]
        prompt_templates = prompt_templates[:12]
        logging.info(
            'Successfully loaded 12 candidates and 12 prompt templates')
        for template in prompt_templates:
            template_id = template['id']
            logging.info(
                f"Processing template {template_id}: {template.get('prompt_version_name', 'unknown')}"
                )
            selected_candidates = random.sample(candidates, 3)
            logging.info(
                f"Selected 3 random candidates: {[c['id'] for c in selected_candidates]}"
                )
            for candidate in selected_candidates:
                candidate_id = candidate['id']
                logging.info(f'Processing candidate {candidate_id}')
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id FROM baqr_prompt_template_nl_questions 
                    WHERE baqr_prompt_template_id = %s AND bird_question_linked_to_cluster_id = %s
                    """
                    , (template_id, candidate_id))
                exists = cursor.fetchone()
                cursor.close()
                conn.close()
                if exists:
                    logging.info(
                        f'Entry already exists for template {template_id} and candidate {candidate_id}, skipping'
                        )
                    continue
                prompt = prepare_prompt(template, candidate)
                response_text = query_flash(prompt)
                if not response_text:
                    logging.error(
                        f'Empty response from Flash for template {template_id} and candidate {candidate_id}'
                        )
                    continue
                if store_response(template_id, candidate_id, response_text):
                    logging.info(
                        f'Successfully processed template {template_id} and candidate {candidate_id}'
                        )
                else:
                    logging.error(
                        f'Failed to store response for template {template_id} and candidate {candidate_id}'
                        )
        elapsed_time = time.time() - start_time
        logging.info(f'Script completed in {elapsed_time:.2f} seconds')
    except Exception as e:
        logging.error(f'Script failed with error: {str(e)}')
        logging.error(traceback.format_exc())


if __name__ == '__main__':
    main()
