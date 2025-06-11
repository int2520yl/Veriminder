import os
import json
import logging
import mysql.connector
from mysql.connector import Error
import time
from datetime import datetime
import traceback
from google import genai
from google.genai import types
os.makedirs('logs', exist_ok=True)
logging.basicConfig(filename='logs/baqr_prompt_self_reflection.log', level=
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
DB_CONFIG = {
    'host': 'YOUR_DATABASE_HOST',
    'port': 'YOUR_DATABASE_POST',
    'user': 'YOUR_DATABASE_USER',
    'password': 'YOUR_DATABASE_PASSWORD',
    'database': 'YOUR_DATABASE_NAME'
}

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
BATCH_SIZE = 5


def get_db_connection():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except Error as e:
        logging.error(f'Database connection error: {str(e)}')
        raise


def get_pending_nl_questions():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT COUNT(*) as count 
            FROM baqr_prompt_template_nl_questions 
            WHERE status='processing_reflection'
        """
            )
        result = cursor.fetchone()
        if result and result['count'] > 0:
            logging.error(
                f"Found {result['count']} records in 'processing_reflection' state. Aborting."
                )
            cursor.close()
            conn.close()
            raise Exception(
                "Found records in 'processing_reflection' state. Fix these before running again."
                )
        cursor.execute(
            """
            SELECT id, baqr_prompt_template_id, bird_question_linked_to_cluster_id, 
                   refinement_question_with_explanation_set, feedback_from_critic_1, feedback_from_critic_2
            FROM baqr_prompt_template_nl_questions 
            WHERE status='success' 
              AND reflection_on_strength_weakness_of_prompt IS NULL
            LIMIT %s
            """
            , (BATCH_SIZE,))
        questions = cursor.fetchall()
        if questions:
            ids = [q['id'] for q in questions]
            placeholders = ', '.join(['%s'] * len(ids))
            cursor.execute(
                f"""
                UPDATE baqr_prompt_template_nl_questions 
                SET status='processing_reflection' 
                WHERE id IN ({placeholders})
                """
                , ids)
            conn.commit()
        cursor.close()
        conn.close()
        logging.info(
            f'Retrieved {len(questions)} questions for self-reflection')
        return questions
    except Exception as e:
        logging.error(f'Error getting pending questions: {str(e)}')
        raise


def get_prompt_template_details(prompt_template_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, prompt_version_name, key_focus, approach_summary, 
                   steps_flow, detailed_prompt
            FROM baqr_prompt_template
            WHERE id = %s
            """
            , (prompt_template_id,))
        template = cursor.fetchone()
        cursor.close()
        conn.close()
        for field in ['key_focus', 'approach_summary', 'steps_flow',
            'detailed_prompt']:
            if isinstance(template[field], str):
                try:
                    template[field] = json.loads(template[field])
                except:
                    pass
        return template
    except Exception as e:
        logging.error(f'Error getting prompt template details: {str(e)}')
        raise


def get_bird_question_details(bird_question_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, bird_question_id, question_text, decision_text, cluster_id,
                   case_study_type, why_decision_question_pair_included, quality_score_for_inclusion
            FROM bird_question_linked_to_cluster
            WHERE id = %s
            """
            , (bird_question_id,))
        question = cursor.fetchone()
        cursor.close()
        conn.close()
        if question and isinstance(question[
            'why_decision_question_pair_included'], str):
            try:
                question['why_decision_question_pair_included'] = json.loads(
                    question['why_decision_question_pair_included'])
            except:
                pass
        return question
    except Exception as e:
        logging.error(f'Error getting bird question details: {str(e)}')
        raise


def create_self_reflection_prompt(nl_question_record):
    try:
        prompt_template = get_prompt_template_details(nl_question_record[
            'baqr_prompt_template_id'])
        bird_question = get_bird_question_details(nl_question_record[
            'bird_question_linked_to_cluster_id'])
        generated_questions = nl_question_record[
            'refinement_question_with_explanation_set']
        if isinstance(generated_questions, str):
            try:
                generated_questions = json.loads(generated_questions)
            except:
                pass
        critic_feedback_1 = nl_question_record['feedback_from_critic_1']
        if isinstance(critic_feedback_1, str):
            try:
                critic_feedback_1 = json.loads(critic_feedback_1)
            except:
                pass
        critic_feedback_2 = nl_question_record['feedback_from_critic_2']
        if isinstance(critic_feedback_2, str):
            try:
                critic_feedback_2 = json.loads(critic_feedback_2)
            except:
                pass
        detailed_prompt = prompt_template['detailed_prompt']
        if isinstance(detailed_prompt, str):
            try:
                detailed_prompt = json.loads(detailed_prompt)
            except:
                pass
        prompt = f"""
You are an **expert prompt engineer** performing a **self-reflection** on a prompt that was used to generate data-analysis refinement questions. The ultimate goal is to **merge the best insights** from your original approach (the prompt's intent), the **actual generated questions**, and the **feedback from multiple critics** into a **single improved prompt** that mitigates weaknesses and amplifies strengths.

Your reflection must be **hierarchical**, covering:
1. **Initial Prompt Goals & Assumptions**:
   - What was the original conviction or purpose behind this prompt?
   - How were frameworks (Toulmin, Vulnerability, etc.) intended to be used?

2. **Outcomes & Self-Evaluation**:
   - How well did the actual generated questions fulfill these goals?
   - Identify any unexpected results or oversights in the generated questions.

3. **Critic Feedback Integration**:
   - Summarize key points from each critic (where do they agree or diverge?).
   - Discuss how you, as the self-reflecting entity, interpret and weigh each critic's remarks.
   - Combine or reconcile conflicting feedback if possible.

4. **Hierarchical Step-by-Step Improvement Plan**:
   - For each significant stage or pillar (e.g., data answerability, structure clarity, bias detection, etc.), provide:
     - **Importance weight**: how crucial is this aspect to final question quality? (1-5)
     - **Your current performance score**: how well did the prompt address it? (1-10)
     - **Confidence in your scoring**: how certain are you about that assessment? (low, medium, high)
     - **Proposed improvement**: the specific, actionable changes needed.
     - **Potential alternatives**: optional or additional expansions if multiple solutions are available.

5. **Merged or Updated Prompt Options**:
   - If you see multiple plausible improvements that each have merits, propose them as "candidate expansions" to the prompt.
   - If you can unify them into one single improved version, outline how.

6. **Concluding Reflection**:
   - Overall self-confidence score (1-10) that your improvements address the main criticisms.
   - Potential blind spots that might still remain.

Below is the original prompt used to generate the refinement questions:

```
{json.dumps(detailed_prompt, indent=2) if isinstance(detailed_prompt, dict) else detailed_prompt}
```

- **Original Bird Question**: {bird_question['question_text']}
- **Decision Context**: {bird_question['decision_text']}

```
{json.dumps(generated_questions, indent=2)}
```

```
{json.dumps(critic_feedback_1, indent=2)}
```

```
{json.dumps(critic_feedback_2, indent=2)}
```

Your reflection must include the prompt ID {prompt_template['id']} and provide thoughtful, detailed analysis for each section. Focus on providing specific insights about the generated questions, the critics' feedback, and concrete recommendations for improving the prompt.
"""
        return prompt
    except Exception as e:
        logging.error(f'Error creating self-reflection prompt: {str(e)}')
        logging.error(traceback.format_exc())
        raise


def get_flash_response_schema():
    response_schema = {'type': 'OBJECT', 'properties': {'prompt_id': {
        'type': 'INTEGER'}, 'self_reflection': {'type': 'OBJECT',
        'properties': {'initial_goals_and_assumptions': {'type': 'OBJECT',
        'properties': {'original_intent': {'type': 'STRING'},
        'framework_utilization': {'type': 'STRING'}}, 'required': [
        'original_intent', 'framework_utilization']},
        'outcomes_and_self_evaluation': {'type': 'OBJECT', 'properties': {
        'observations_on_generated_questions': {'type': 'STRING'},
        'unanticipated_results_or_oversights': {'type': 'STRING'}},
        'required': ['observations_on_generated_questions',
        'unanticipated_results_or_oversights']},
        'critic_feedback_integration': {'type': 'OBJECT', 'properties': {
        'critic_1_key_points': {'type': 'ARRAY', 'items': {'type': 'STRING'
        }}, 'critic_2_key_points': {'type': 'ARRAY', 'items': {'type':
        'STRING'}}, 'agreement_areas': {'type': 'ARRAY', 'items': {'type':
        'STRING'}}, 'divergent_areas': {'type': 'ARRAY', 'items': {'type':
        'STRING'}}, 'unifying_interpretation': {'type': 'STRING'}},
        'required': ['critic_1_key_points', 'critic_2_key_points',
        'agreement_areas', 'divergent_areas', 'unifying_interpretation']},
        'hierarchical_improvement_plan': {'type': 'ARRAY', 'items': {'type':
        'OBJECT', 'properties': {'aspect_name': {'type': 'STRING'},
        'importance_weight': {'type': 'INTEGER'},
        'current_performance_score': {'type': 'INTEGER'},
        'confidence_in_score': {'type': 'STRING'}, 'proposed_improvement':
        {'type': 'STRING'}, 'potential_alternatives': {'type': 'ARRAY',
        'items': {'type': 'STRING'}}}, 'required': ['aspect_name',
        'importance_weight', 'current_performance_score',
        'confidence_in_score', 'proposed_improvement']}},
        'merged_or_updated_prompt_options': {'type': 'OBJECT', 'properties':
        {'single_improved_version': {'type': 'STRING'},
        'alternate_candidate_expansions': {'type': 'ARRAY', 'items': {
        'type': 'STRING'}}}, 'required': ['single_improved_version']},
        'concluding_reflection': {'type': 'OBJECT', 'properties': {
        'overall_self_confidence_score': {'type': 'INTEGER'},
        'remaining_blind_spots': {'type': 'STRING'}}, 'required': [
        'overall_self_confidence_score', 'remaining_blind_spots']}},
        'required': ['initial_goals_and_assumptions',
        'outcomes_and_self_evaluation', 'critic_feedback_integration',
        'hierarchical_improvement_plan', 'merged_or_updated_prompt_options',
        'concluding_reflection']}}, 'required': ['prompt_id',
        'self_reflection']}
    return response_schema


def query_flash(content_prompt):
    try:
        logging.info('Sending request to Flash (Gemini) API using streaming')
        logging.info(f'CONTENT PROMPT (truncated): {content_prompt[:500]}...')
        response_schema = get_flash_response_schema()
        generate_content_config = types.GenerateContentConfig(temperature=
            0.2, top_p=0.95, max_output_tokens=8192, response_modalities=[
            'TEXT'], safety_settings=[types.SafetySetting(category=
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
        try:
            response_stream = FLASH_CLIENT.models.generate_content_stream(model
                =FLASH_MODEL, contents=contents, config=generate_content_config
                )
            for chunk in response_stream:
                chunk_text = chunk.text if hasattr(chunk, 'text'
                    ) and chunk.text else ''
                response_text += chunk_text
        except Exception as stream_error:
            logging.error(f'Streaming error: {str(stream_error)}')
            try:
                response = FLASH_CLIENT.models.generate_content(model=
                    FLASH_MODEL, contents=contents, config=
                    generate_content_config)
                response_text = response.text
                logging.info('Successfully fell back to non-streaming API')
            except Exception as fallback_error:
                logging.error(f'Fallback error: {str(fallback_error)}')
                return {}
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        response_file = f'logs/flash_self_reflection_response_{timestamp}.txt'
        with open(response_file, 'w', encoding='utf-8') as f:
            f.write(response_text)
        logging.info(f'Full response saved to {response_file}')
        try:
            json_output = json.loads(response_text)
            return json_output
        except json.JSONDecodeError as e:
            logging.error(f'Failed to parse JSON from Flash response: {str(e)}'
                )
            error_file = f'logs/json_parse_error_{timestamp}.txt'
            with open(error_file, 'w', encoding='utf-8') as f:
                f.write(response_text)
            return {}
    except Exception as e:
        logging.error(f'Error calling Flash API: {str(e)}')
        logging.error(traceback.format_exc())
        return {}


def update_reflection(nl_question_id, reflection_data):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE baqr_prompt_template_nl_questions 
            SET reflection_on_strength_weakness_of_prompt = %s, status = 'reflection_complete'
            WHERE id = %s
            """
            , (json.dumps(reflection_data), nl_question_id))
        conn.commit()
        cursor.close()
        conn.close()
        logging.info(f'Updated reflection for nl_question ID {nl_question_id}')
        return True
    except Exception as e:
        logging.error(f'Error updating reflection: {str(e)}')
        return False


def main():
    start_time = time.time()
    logging.info(
        'Starting baqr_prompt_self_reflection.py script (extended version)')
    try:
        total_processed = 0
        while True:
            nl_questions = get_pending_nl_questions()
            if not nl_questions:
                logging.info(
                    f'No more questions for reflection. Total processed so far: {total_processed}'
                    )
                break
            for question_record in nl_questions:
                question_id = question_record['id']
                logging.info(
                    f'Processing reflection for nl_question ID={question_id}')
                try:
                    prompt = create_self_reflection_prompt(question_record)
                    reflection_data = query_flash(prompt)
                    if not reflection_data:
                        logging.error(
                            f'No or invalid JSON response from Flash for question {question_id}. Marking failed.'
                            )
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE baqr_prompt_template_nl_questions SET status='reflection_failed' WHERE id=%s"
                            , (question_id,))
                        conn.commit()
                        cursor.close()
                        conn.close()
                        continue
                    if update_reflection(question_id, reflection_data):
                        logging.info(
                            f'Reflection successfully stored for question {question_id}'
                            )
                        total_processed += 1
                    else:
                        logging.error(
                            f'Reflection update failed for question {question_id}. Marking as reflection_failed.'
                            )
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE baqr_prompt_template_nl_questions SET status='reflection_failed' WHERE id=%s"
                            , (question_id,))
                        conn.commit()
                        cursor.close()
                        conn.close()
                except Exception as e:
                    logging.error(
                        f'Error processing reflection for question {question_id}: {str(e)}'
                        )
                    logging.error(traceback.format_exc())
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE baqr_prompt_template_nl_questions SET status='reflection_failed' WHERE id=%s"
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
