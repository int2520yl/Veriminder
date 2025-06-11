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
logging.basicConfig(filename='logs/moe_prompt_builder.log', level=logging.
    INFO, format=
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
SAMPLE_PROMPT_PATH = 'sample_prompt.txt'


def get_db_connection():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except Error as e:
        logging.error(f'Database connection error: {str(e)}')
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


def get_template_reflections(template_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT reflection_on_strength_weakness_of_prompt
            FROM baqr_prompt_template_nl_questions
            WHERE baqr_prompt_template_id = %s
            AND reflection_on_strength_weakness_of_prompt IS NOT NULL
            AND status = 'reflection_complete'
            """
            , (template_id,))
        reflections = cursor.fetchall()
        cursor.close()
        conn.close()
        logging.info(
            f'Retrieved {len(reflections)} reflections for template ID {template_id}'
            )
        return reflections
    except Exception as e:
        logging.error(f'Error getting template reflections: {str(e)}')
        raise


def read_sample_prompt():
    try:
        with open(SAMPLE_PROMPT_PATH, 'r') as file:
            return file.read()
    except Exception as e:
        logging.error(f'Error reading sample prompt: {str(e)}')
        raise


def extract_prompt_text(prompt_data):
    if isinstance(prompt_data, str):
        try:
            prompt_json = json.loads(prompt_data)
            if isinstance(prompt_json, dict):
                if 'text' in prompt_json:
                    return prompt_json['text']
                elif 'content' in prompt_json:
                    return prompt_json['content']
                elif 'prompt' in prompt_json:
                    return prompt_json['prompt']
        except:
            return prompt_data
    elif isinstance(prompt_data, dict):
        if 'text' in prompt_data:
            return prompt_data['text']
        elif 'content' in prompt_data:
            return prompt_data['content']
        elif 'prompt' in prompt_data:
            return prompt_data['prompt']
    return str(prompt_data)


def get_flash_response_schema():
    response_schema = {'type': 'OBJECT', 'properties': {'prompt_name': {
        'type': 'STRING'}, 'prompt_description': {'type': 'STRING'},
        'detailed_prompt': {'type': 'STRING'}}, 'required': ['prompt_name',
        'prompt_description', 'detailed_prompt']}
    return response_schema


def create_optimization_prompt(sample_prompt, prompt_templates,
    template_reflections):
    detailed_prompts = []
    for i, template in enumerate(prompt_templates[:5], 1):
        prompt_text = extract_prompt_text(template.get('detailed_prompt', ''))
        detailed_prompts.append(
            f"""PROMPT {i} ({template['prompt_version_name']}):
{prompt_text[:800]}...
"""
            )
    reflection_excerpts = []
    for template_id, reflections in template_reflections.items():
        if len(reflections) > 0:
            reflection_count = 0
            for reflection in reflections[:3]:
                reflection_text = reflection.get(
                    'reflection_on_strength_weakness_of_prompt', '')
                if isinstance(reflection_text, str):
                    try:
                        reflection_json = json.loads(reflection_text)
                        if isinstance(reflection_json, dict
                            ) and 'self_reflection' in reflection_json:
                            reflection_data = reflection_json['self_reflection'
                                ]
                            strengths = []
                            weaknesses = []
                            if ('hierarchical_improvement_plan' in
                                reflection_data):
                                for item in reflection_data[
                                    'hierarchical_improvement_plan']:
                                    if item.get('current_performance_score', 0
                                        ) >= 7:
                                        strengths.append(
                                            f"- {item.get('aspect_name')}: {item.get('proposed_improvement')}"
                                            )
                                    else:
                                        weaknesses.append(
                                            f"- {item.get('aspect_name')}: {item.get('proposed_improvement')}"
                                            )
                            reflection_excerpts.append(
                                f"""REFLECTION FOR PROMPT {template_id}:
Strengths:
"""
                                 + '\n'.join(strengths) + '\nWeaknesses:\n' +
                                '\n'.join(weaknesses) + '\n')
                            reflection_count += 1
                    except:
                        reflection_excerpts.append(
                            f"""REFLECTION FOR PROMPT {template_id} (raw):
{reflection_text[:500]}...
"""
                            )
                        reflection_count += 1
            if reflection_count == 0:
                reflection_excerpts.append(
                    f"""NO DETAILED REFLECTIONS AVAILABLE FOR PROMPT {template_id}
"""
                    )
    prompt = f"""
You are an expert prompt engineer tasked with creating a comprehensive, enhanced prompt for an AI system that generates insightful refinement questions to support data-driven decisions. Your goal is to create ONE unified prompt that combines the strengths from various prompt templates and addresses the weaknesses identified in reflections.

The BAQR (Better Analysis through Quality Refinement) system helps users make better decisions by generating thought-provoking questions when provided with a decision scenario. The AI needs to:
1. Generate one primary question based on the user's original question
2. Generate upto 5 refinement questions that help create "hard-to-vary" explanations

A "hard-to-vary" explanation has these essential characteristics:
- Each component has a specific, data-constrained meaning
- Components cannot be arbitrarily modified without breaking the explanation
- The explanation is falsifiable by specific data conditions
- It addresses potential cognitive biases and counterarguments preemptively

The AI system has access to these resources:
- Evidence: '{EVIDENCE_FILE_PATH}'
- Schema: '{SCHEMA_FILE_PATH}'
- Stats: '{STATS_FILE_PATH}'
- Pillar Directory: '{PILLAR_DIR}'
- Toulmin Structure: '{TOULMIN_FILE_PATH}'
- Dataset Schema: '{DATASET_SCHEMA_FILE_PATH}'
- Vulnerability Frames: '{VULNERABILITY_FILE_PATH}'
- Counterargument Patterns: '{COUNTERARGUMENT_FILE_PATH}'

Create ONE comprehensive, well-structured prompt that:

1. Focuses on generating questions that can be readily converted to SQL statements
2. Uses the schema and evidence resources as constraints
3. Emphasizes "hard-to-vary" principles but makes them decision-focused
4. Is adaptive based on decision type and question type
5. Combines the strengths from various prompt templates and addresses the weaknesses identified in reflections
6. Stays true to the core principles and pillars
7. Is clear, concise, and well-organized

Here is a sample prompt that can serve as a foundation:

{sample_prompt[:20000]}...

The following are excerpts from different prompt variations that have been used:

{''.join(detailed_prompts)}

The following reflections highlight strengths and weaknesses of various prompts:

{''.join(reflection_excerpts)}

Your output should be a single JSON object with the following fields:
1. "prompt_name": A descriptive name for your optimized prompt
2. "prompt_description": A brief description of the key features and focus of your prompt
3. "detailed_prompt": The full text of your optimized prompt, ready to be used directly with an AI model


1. Make the prompt clear and actionable with a clear structure
2. Emphasize that questions must be specific and directly answerable with SQL queries
3. Focus on creating questions that lead to "hard-to-vary" explanations
4. Balance theoretical frameworks with practical data accessibility
5. Make sure your prompt specifically addresses how to:
   - Use the provided frameworks (Toulmin, Vulnerability, etc.) effectively
   - Generate specific, data-constrained questions
   - Create questions that expose potential biases
   - Create questions that can be readily translated to SQL
   - Prioritize decision relevance over comprehensiveness
6. Include a concise example of a good question vs. a poor question
7. Make sure but the content can fit into 8192 tokens response size limit

Your optimized prompt should represent a significant improvement over the sample prompt as well as incorporate ALL the insights from the self reflections from the candidate prompts  by incorporating the strengths and addressing the weaknesses identified in the reflections.
"""
    return prompt


def query_flash(content_prompt):
    try:
        logging.info('Sending request to Flash (Gemini) API using streaming')
        logging.info(f'CONTENT PROMPT (truncated): {content_prompt[:300]}...')
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
            for chunk in FLASH_CLIENT.models.generate_content_stream(model=
                FLASH_MODEL, contents=contents, config=generate_content_config
                ):
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
                logging.info('Successfully used non-streaming API as fallback')
            except Exception as fallback_error:
                logging.error(f'Fallback error: {str(fallback_error)}')
                return {}
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        response_file = f'logs/flash_optimized_prompt_{timestamp}.txt'
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


def save_optimized_prompt(optimized_prompt):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        prompt_name = optimized_prompt.get('prompt_name',
            'MOE Optimized Prompt')
        prompt_description = optimized_prompt.get('prompt_description', '')
        detailed_prompt = optimized_prompt.get('detailed_prompt', '')
        prompt_json = {'text': detailed_prompt}
        key_focus = {'focus':
            'Optimized prompt combining strengths from multiple templates',
            'description': prompt_description}
        approach_summary = {'methodology': 'MOE (Mixture of Experts)',
            'key_principles': ['Hard-to-vary explanations',
            'SQL-convertible questions', 'Decision-focused refinement',
            'Bias mitigation']}
        steps_flow = {'process':
            'Automated optimization based on template reflections',
            'source': 'Multiple template strengths combined'}
        cursor.execute(
            """
            INSERT INTO baqr_prompt_template 
            (prompt_version_name, source, key_focus, approach_summary, steps_flow, detailed_prompt, status, version) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            , (prompt_name, 'optimized_moe', json.dumps(key_focus), json.
            dumps(approach_summary), json.dumps(steps_flow), json.dumps(
            prompt_json), 'active', 1))
        inserted_id = cursor.lastrowid
        conn.commit()
        cursor.close()
        conn.close()
        logging.info(
            f'Saved optimized prompt to database with ID {inserted_id}')
        return inserted_id
    except Exception as e:
        logging.error(f'Error saving optimized prompt: {str(e)}')
        return None


def main():
    start_time = time.time()
    logging.info('Starting moe_prompt_builder.py script')
    try:
        sample_prompt = read_sample_prompt()
        logging.info('Successfully read sample prompt')
        templates = get_prompt_templates()
        logging.info(f'Retrieved {len(templates)} prompt templates')
        template_reflections = {}
        for template in templates:
            template_id = template['id']
            reflections = get_template_reflections(template_id)
            if reflections:
                template_reflections[template_id] = reflections
        logging.info(
            f'Retrieved reflections for {len(template_reflections)} templates')
        optimization_prompt = create_optimization_prompt(sample_prompt,
            templates, template_reflections)
        optimized_prompt = query_flash(optimization_prompt)
        logging.info('Generated optimized prompt')
        if optimized_prompt:
            prompt_id = save_optimized_prompt(optimized_prompt)
            if prompt_id:
                logging.info(
                    f'Successfully saved optimized prompt with ID {prompt_id}')
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                output_file = f'optimized_prompt_{timestamp}.txt'
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(optimized_prompt.get('detailed_prompt', ''))
                logging.info(f'Saved optimized prompt to {output_file}')
            else:
                logging.error('Failed to save optimized prompt')
        else:
            logging.error('No optimized prompt generated')
        elapsed_time = time.time() - start_time
        logging.info(f'Script completed in {elapsed_time:.2f} seconds')
    except Exception as e:
        logging.error(f'Script failed with error: {str(e)}')
        logging.error(traceback.format_exc())


if __name__ == '__main__':
    main()
