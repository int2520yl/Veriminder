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
logging.basicConfig(filename='logs/run_critics_on_candidate_data.log',
    level=logging.INFO, format=
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
BATCH_SIZE = 10


def get_db_connection():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except Error as e:
        logging.error(f'Database connection error: {str(e)}')
        raise


def get_pending_questions():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT COUNT(*) as count FROM baqr_prompt_template_nl_questions WHERE status='processing'"
            )
        result = cursor.fetchone()
        if result and result['count'] > 0:
            logging.error(
                f"Found {result['count']} records in 'processing' state. Aborting."
                )
            cursor.close()
            conn.close()
            raise Exception(
                "Found records in 'processing' state. Fix these before running again."
                )
        cursor.execute(
            """
            SELECT id, baqr_prompt_template_id, bird_question_linked_to_cluster_id, refinement_question_with_explanation_set 
            FROM baqr_prompt_template_nl_questions 
            WHERE status='pending_critic'
            LIMIT %s
            """
            , (BATCH_SIZE,))
        questions = cursor.fetchall()
        if questions:
            ids = [q['id'] for q in questions]
            placeholders = ', '.join(['%s'] * len(ids))
            cursor.execute(
                f"UPDATE baqr_prompt_template_nl_questions SET status='processing' WHERE id IN ({placeholders})"
                , ids)
            conn.commit()
        cursor.close()
        conn.close()
        logging.info(
            f'Retrieved {len(questions)} questions for critic evaluation')
        return questions
    except Exception as e:
        logging.error(f'Error getting pending questions: {str(e)}')
        raise


def get_critic_templates():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM baqr_critic_template WHERE status='active'")
        templates = cursor.fetchall()
        cursor.close()
        conn.close()
        logging.info(f'Retrieved {len(templates)} critic templates')
        return templates
    except Exception as e:
        logging.error(f'Error getting critic templates: {str(e)}')
        raise


def get_bird_question_details(bird_question_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT question_text, decision_text 
            FROM bird_question_linked_to_cluster 
            WHERE id = %s
            """
            , (bird_question_id,))
        question = cursor.fetchone()
        cursor.close()
        conn.close()
        return question
    except Exception as e:
        logging.error(f'Error getting bird question details: {str(e)}')
        raise


def get_prompt_template_details(prompt_template_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT prompt_version_name, key_focus, approach_summary 
            FROM baqr_prompt_template 
            WHERE id = %s
            """
            , (prompt_template_id,))
        template = cursor.fetchone()
        cursor.close()
        conn.close()
        return template
    except Exception as e:
        logging.error(f'Error getting prompt template details: {str(e)}')
        raise


def get_flash_response_schema():
    response_schema = {'type': 'OBJECT', 'properties': {'strengths': {
        'type': 'ARRAY', 'items': {'type': 'OBJECT', 'properties': {
        'aspect': {'type': 'STRING'}, 'explanation': {'type': 'STRING'}},
        'required': ['aspect', 'explanation']}}, 'weaknesses': {'type':
        'ARRAY', 'items': {'type': 'OBJECT', 'properties': {'aspect': {
        'type': 'STRING'}, 'explanation': {'type': 'STRING'}}, 'required':
        ['aspect', 'explanation']}}, 'missing_considerations': {'type':
        'ARRAY', 'items': {'type': 'OBJECT', 'properties': {'consideration':
        {'type': 'STRING'}, 'importance': {'type': 'STRING'}}, 'required':
        ['consideration', 'importance']}}, 'overall_assessment': {'type':
        'OBJECT', 'properties': {'effectiveness_score': {'type': 'INTEGER'},
        'justification': {'type': 'STRING'}}, 'required': [
        'effectiveness_score', 'justification']}}, 'required': ['strengths',
        'weaknesses', 'missing_considerations', 'overall_assessment']}
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
        response_file = f'logs/flash_critic_response_{timestamp}.txt'
        with open(response_file, 'w', encoding='utf-8') as f:
            f.write(response_text)
        logging.info(f'Full response saved to {response_file}')
        return response_text
    except Exception as e:
        logging.error(f'Error calling Flash API: {str(e)}')
        logging.error(traceback.format_exc())
        return ''


def prepare_critic_prompt(critic_template, question_record):
    try:
        detailed_prompt_json = critic_template['detailed_prompt']
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
        bird_question = get_bird_question_details(question_record[
            'bird_question_linked_to_cluster_id'])
        prompt_template = get_prompt_template_details(question_record[
            'baqr_prompt_template_id'])
        generated_questions_json = question_record[
            'refinement_question_with_explanation_set']
        if isinstance(generated_questions_json, str):
            generated_questions = json.loads(generated_questions_json)
        else:
            generated_questions = generated_questions_json
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
        prompt_text += f'\n\n# Original Question and Decision Context\n'
        prompt_text += (
            f"Original Question: {bird_question['question_text']}\n\n")
        prompt_text += (
            f"Decision Context: {bird_question['decision_text']}\n\n")
        prompt_text += f'# Prompt Template Used\n'
        prompt_text += (
            f"Template Name: {prompt_template['prompt_version_name']}\n\n")
        prompt_text += f'# Generated Questions for Critique\n'
        prompt_text += (
            f'```json\n{json.dumps(generated_questions, indent=2)}\n```\n\n')
        prompt_text += (
            'Please evaluate the quality of these refinement questions using the framework described above.'
            )
        return prompt_text
    except Exception as e:
        logging.error(f'Error preparing critic prompt: {str(e)}')
        logging.error(traceback.format_exc())
        raise


def update_question_feedback(question_id, critic_number, feedback,
    completed=False):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if completed:
            cursor.execute(
                f"""
                UPDATE baqr_prompt_template_nl_questions 
                SET feedback_from_critic_{critic_number} = %s, status = 'success'
                WHERE id = %s
                """
                , (feedback, question_id))
        else:
            cursor.execute(
                f"""
                UPDATE baqr_prompt_template_nl_questions 
                SET feedback_from_critic_{critic_number} = %s
                WHERE id = %s
                """
                , (feedback, question_id))
        conn.commit()
        cursor.close()
        conn.close()
        logging.info(
            f'Updated feedback from critic {critic_number} for question {question_id}'
            )
        return True
    except Exception as e:
        logging.error(f'Error updating question feedback: {str(e)}')
        return False


def main():
    start_time = time.time()
    logging.info('Starting run_critics_on_candidate_data.py script')
    try:
        critic_templates = get_critic_templates()
        if len(critic_templates) < 3:
            logging.error(
                f'Expected at least 3 critic templates, but found {len(critic_templates)}'
                )
            raise ValueError(
                f'Expected at least 3 critic templates, but found {len(critic_templates)}'
                )
        critic_templates = critic_templates[:3]
        logging.info(
            f"Using critic templates: {[c['id'] for c in critic_templates]}")
        total_processed = 0
        while True:
            questions = get_pending_questions()
            if not questions:
                logging.info(
                    f'No more questions found for critic evaluation. Total processed: {total_processed}'
                    )
                break
            for question in questions:
                question_id = question['id']
                logging.info(f'Processing question {question_id}')
                try:
                    selected_critics = random.sample(critic_templates, 2)
                    logging.info(
                        f"Selected 2 random critics: {[c['id'] for c in selected_critics]}"
                        )
                    for i, critic in enumerate(selected_critics, 1):
                        critic_id = critic['id']
                        logging.info(
                            f'Applying critic {critic_id} as critic_{i} to question {question_id}'
                            )
                        prompt = prepare_critic_prompt(critic, question)
                        response_text = query_flash(prompt)
                        if not response_text:
                            logging.error(
                                f'Empty response from Flash for critic {critic_id} and question {question_id}'
                                )
                            continue
                        is_last_critic = i == len(selected_critics)
                        update_question_feedback(question_id, i,
                            response_text, completed=is_last_critic)
                    logging.info(
                        f'Successfully processed question {question_id}')
                    total_processed += 1
                except Exception as e:
                    logging.error(
                        f'Error processing question {question_id}: {str(e)}')
                    logging.error(traceback.format_exc())
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE baqr_prompt_template_nl_questions SET status = 'failed' WHERE id = %s"
                        , (question_id,))
                    conn.commit()
                    cursor.close()
                    conn.close()
        elapsed_time = time.time() - start_time
        logging.info(
            f'Script completed in {elapsed_time:.2f} seconds. Total processed: {total_processed}'
            )
    except Exception as e:
        logging.error(f'Script failed with error: {str(e)}')
        logging.error(traceback.format_exc())


if __name__ == '__main__':
    main()
