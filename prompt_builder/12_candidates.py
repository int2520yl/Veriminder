import os
import json
import logging
import anthropic
import mysql.connector
from mysql.connector import Error
import time
from datetime import datetime
import traceback
os.makedirs('logs', exist_ok=True)
logging.basicConfig(filename='logs/baqr_candidate_prompts.log', level=
    logging.INFO, format=
    '%(asctime)s - %(levelname)s - %(pathname)s:%(lineno)d - %(message)s')
DB_CONFIG = {
    'host': 'YOUR_DATABASE_HOST',
    'port': 'YOUR_DATABASE_POST',
    'user': 'YOUR_DATABASE_USER',
    'password': 'YOUR_DATABASE_PASSWORD',
    'database': 'YOUR_DATABASE_NAME'
}

CLAUDE_API_KEY = (
    'ENTER_KEY'
    )
CLAUDE_CLIENT = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
SAMPLE_PROMPT_PATH = 'sample_prompt.txt'
RESOURCE_PATHS = {'evidence_path': '../data/all_evidence.json',
    'schema_path': '../data/BIRD_table_schema_info.json', 'stats_path':
    '../data/compact_dataset_stats.json', 'pillar_dir':
    '../resources/question_guide_pillars/', 'toulmin_path':
    '../resources/question_guide_pillars/toulmin_argument_structure.json',
    'dataset_schema_path':
    '../resources/question_guide_pillars/dataset_schema_based_patterns.json',
    'vulnerability_path':
    '../resources/question_guide_pillars/vulnerability_semantic_frames.json',
    'counterargument_path':
    '../resources/question_guide_pillars/preemptive-counterargument_pattern.json'
    }


def get_db_connection():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except Error as e:
        logging.error(f'Database connection error: {str(e)}')
        raise


def read_sample_prompt():
    try:
        with open(SAMPLE_PROMPT_PATH, 'r') as file:
            return file.read()
    except Exception as e:
        logging.error(f'Error reading sample prompt: {str(e)}')
        raise


def create_claude_prompt(sample_prompt):
    prompt = f"""
You are an expert prompt engineer specializing in designing prompts for AI systems that create robust data analysis questions. Your task is to create 12 distinct prompt variations for an AI that generates insightful questions to support data-driven decisions.

I'm developing an AI system that helps users make better decisions by generating thought-provoking questions. When provided with a decision scenario, the AI needs to:
1. Generate one primary question based on the user's original question
2. Generate 3-5 refinement questions that help create "hard-to-vary" explanations

A "hard-to-vary" explanation has these essential characteristics:
- Each component has a specific, data-constrained meaning
- Components cannot be arbitrarily modified without breaking the explanation
- The explanation is falsifiable by specific data conditions
- It addresses potential cognitive biases and counterarguments preemptively

The AI system has access to these frameworks/resources that should be incorporated into your prompts:

1. **Vulnerability Semantic Frames** - Identifies cognitive biases that affect decision-making
2. **Dataset Schema Patterns** - Helps validate data structure considerations
3. **Toulmin Argument Structure** - Framework for forming robust data-driven arguments
4. **Preemptive Counterargument Patterns** - Structured approaches for challenging decisions

Each prompt should reference these paths that will be passed as parameters:
- Evidence: '{RESOURCE_PATHS['evidence_path']}'
- Schema: '{RESOURCE_PATHS['schema_path']}'
- Stats: '{RESOURCE_PATHS['stats_path']}'
- Pillar Directory: '{RESOURCE_PATHS['pillar_dir']}'
- Toulmin Structure: '{RESOURCE_PATHS['toulmin_path']}'
- Dataset Schema: '{RESOURCE_PATHS['dataset_schema_path']}'
- Vulnerability Frames: '{RESOURCE_PATHS['vulnerability_path']}'
- Counterargument Patterns: '{RESOURCE_PATHS['counterargument_path']}'

Create 12 distinct prompt variations that Claude will use to generate refined questions. Each prompt should:

1. Have a unique approach or emphasis on using the frameworks
2. Include all necessary context about hard-to-vary explanations
3. Reference the resource paths above
4. Structure the prompt to elicit high-quality, specific questions
5. Include concrete examples or guidance on what makes good questions
6. Have a clear output format

Below is a sample prompt that has been used previously. Your 12 variations should be distinctly different from this sample, while maintaining the core objective:

{sample_prompt}

For each prompt variation, provide:

1. **prompt_version_name**: A descriptive name for this prompt variation
2. **source**: "claude_generated"
3. **key_focus**: JSON object describing the primary focus of this prompt variation
4. **approach_summary**: JSON object explaining how this prompt approaches generating questions
5. **steps_flow**: JSON object detailing the logical steps/algorithm the prompt uses
6. **detailed_prompt**: JSON object containing the complete prompt text

Return your response as a JSON array containing 12 objects, each with the above fields.

Each prompt should be comprehensive and focus on different aspects or combinations of the frameworks. Be creative in how the frameworks are used while ensuring all prompts will generate questions that help build hard-to-vary explanations for decision-making.

THE DETAILED_PROMPT SHOULD BE COMPLETE, COMPREHENSIVE, AND READY TO BE USED DIRECTLY WITH THE AI MODEL.
"""
    return prompt


def query_claude(prompt):
    try:
        logging.info(
            'Sending request to Claude API using streaming with extended reasoning'
            )
        logging.info(f'PROMPT (truncated):\n{prompt[:1000]}...')
        response_text = ''
        thinking_text = ''
        with CLAUDE_CLIENT.beta.messages.stream(model=
            'claude-3-7-sonnet-20250219', max_tokens=128000, thinking={
            'type': 'enabled', 'budget_tokens': 60000}, messages=[{'role':
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
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        response_file = f'logs/claude_prompt_response_{timestamp}.txt'
        thinking_file = f'logs/claude_prompt_thinking_{timestamp}.txt'
        with open(response_file, 'w', encoding='utf-8') as f:
            f.write(response_text)
        with open(thinking_file, 'w', encoding='utf-8') as f:
            f.write(thinking_text)
        logging.info(f'Full response saved to {response_file}')
        logging.info(f'Thinking saved to {thinking_file}')
        try:
            json_start = response_text.find('[')
            if json_start >= 0:
                json_end = response_text.rfind(']') + 1
                if json_end > json_start:
                    json_str = response_text[json_start:json_end]
                    return json.loads(json_str)
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
            logging.error('Could not find JSON data in response')
            return []
        except json.JSONDecodeError as e:
            logging.error(f'Error parsing JSON: {str(e)}')
            with open(f'logs/json_parse_error_{timestamp}.txt', 'w',
                encoding='utf-8') as f:
                f.write(json_str if 'json_str' in locals() else
                    'JSON string not identified')
            return []
    except Exception as e:
        logging.error(f'Error calling Claude API: {str(e)}')
        logging.error(traceback.format_exc())
        return []


def store_prompts_in_db(prompts):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        stored_count = 0
        for prompt in prompts:
            try:
                prompt_version_name = prompt.get('prompt_version_name', '')
                source = prompt.get('source', 'claude_generated')
                key_focus = json.dumps(prompt.get('key_focus', {}))
                approach_summary = json.dumps(prompt.get('approach_summary',
                    {}))
                steps_flow = json.dumps(prompt.get('steps_flow', {}))
                detailed_prompt = json.dumps(prompt.get('detailed_prompt', {}))
                cursor.execute(
                    """
                    INSERT INTO baqr_prompt_template 
                    (prompt_version_name, source, key_focus, approach_summary, steps_flow, detailed_prompt, status) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """
                    , (prompt_version_name, source, key_focus,
                    approach_summary, steps_flow, detailed_prompt, 'active'))
                stored_count += 1
                logging.info(
                    f"Inserted prompt '{prompt_version_name}' into database")
            except Exception as e:
                logging.error(
                    f"Error storing prompt '{prompt.get('prompt_version_name', 'unknown')}': {str(e)}"
                    )
                logging.error(traceback.format_exc())
                continue
        conn.commit()
        cursor.close()
        conn.close()
        logging.info(
            f'Successfully stored {stored_count} of {len(prompts)} prompts in database'
            )
        return stored_count > 0
    except Exception as e:
        logging.error(f'Error in store_prompts_in_db: {str(e)}')
        logging.error(traceback.format_exc())
        return False


def main():
    start_time = time.time()
    logging.info('Starting baqr_candidate_prompts.py script')
    try:
        sample_prompt = read_sample_prompt()
        logging.info('Successfully read sample prompt')
        claude_prompt = create_claude_prompt(sample_prompt)
        prompts = query_claude(claude_prompt)
        logging.info(f'Generated {len(prompts)} prompt variations')
        if prompts:
            if store_prompts_in_db(prompts):
                logging.info('Successfully stored prompts in database')
            else:
                logging.error('Failed to store prompts in database')
        else:
            logging.error('No prompts generated')
        elapsed_time = time.time() - start_time
        logging.info(f'Script completed in {elapsed_time:.2f} seconds')
    except Exception as e:
        logging.error(f'Script failed with error: {str(e)}')
        logging.error(traceback.format_exc())


if __name__ == '__main__':
    main()
