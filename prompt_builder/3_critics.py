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
logging.basicConfig(filename='logs/create_critic_templates.log', level=
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


def create_claude_prompt():
    prompt = f"""
You are an expert prompt engineer specializing in designing prompts for AI systems that evaluate data analysis questions. Your task is to create 3 distinct prompt variations for an AI critic that evaluates the quality of refinement questions for data-driven decisions.

I'm developing a BAQR (Better Analysis through Quality Refinement) system with two AI components:
1. A question generator that creates refinement questions based on a user's decision scenario
2. A critic agent that evaluates the strengths and weaknesses of these generated questions

Your task is to design prompts for the critic agent. The critic will review sets of refinement questions and provide constructive feedback on their strengths, weaknesses, and any unanswered aspects.

Both the generator and critic should support building "hard-to-vary" explanations, which have these essential characteristics:
- Each component has a specific, data-constrained meaning
- Components cannot be arbitrarily modified without breaking the explanation
- The explanation is falsifiable by specific data conditions
- It addresses potential cognitive biases and counterarguments preemptively

The critic AI has access to these frameworks/resources:

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

Create 3 distinct prompt variations for the critic agent. Each prompt should:

1. Have a unique approach or emphasis on using the frameworks to evaluate questions
2. Include all necessary context about hard-to-vary explanations
3. Reference the resource paths above
4. Structure the prompt to elicit high-quality, constructive criticism
5. Include concrete examples or guidance on what makes good feedback
6. Have a clear output format for the critic's feedback
7. Not assume anything about how the original questions were generated (the critic should not know that the generator used the same principles)

1. The critic should evaluate whether the refinement questions help build hard-to-vary explanations
2. The critic should focus on the questions themselves, not on the user's original problem statement
3. The critic should identify both strengths and weaknesses
4. The critic should suggest what important questions might be missing
5. The critic's feedback should be constructive and actionable

For each prompt variation, provide:

1. **critic_version_name**: A descriptive name for this critic prompt variation
2. **source**: "claude_generated"
3. **key_focus**: JSON object describing the primary focus of this critic prompt
4. **approach_summary**: JSON object explaining how this prompt approaches critiquing questions
5. **steps_flow**: JSON object detailing the logical steps/algorithm the prompt uses
6. **detailed_prompt**: JSON object containing the complete prompt text

Return your response as a JSON array containing 3 objects, each with the above fields.

Each prompt should be comprehensive and focus on different aspects or combinations of the frameworks. Be creative in how the frameworks are used to evaluate questions.

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
        response_file = f'logs/claude_critic_response_{timestamp}.txt'
        thinking_file = f'logs/claude_critic_thinking_{timestamp}.txt'
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
                critic_version_name = prompt.get('critic_version_name', '')
                source = prompt.get('source', 'claude_generated')
                key_focus = json.dumps(prompt.get('key_focus', {}))
                approach_summary = json.dumps(prompt.get('approach_summary',
                    {}))
                steps_flow = json.dumps(prompt.get('steps_flow', {}))
                detailed_prompt = json.dumps(prompt.get('detailed_prompt', {}))
                cursor.execute(
                    """
                    INSERT INTO baqr_critic_template 
                    (critic_version_name, source, key_focus, approach_summary, steps_flow, detailed_prompt, status, version) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    , (critic_version_name, source, key_focus,
                    approach_summary, steps_flow, detailed_prompt, 'active', 1)
                    )
                stored_count += 1
                logging.info(
                    f"Inserted critic prompt '{critic_version_name}' into database"
                    )
            except Exception as e:
                logging.error(
                    f"Error storing critic prompt '{prompt.get('critic_version_name', 'unknown')}': {str(e)}"
                    )
                logging.error(traceback.format_exc())
                continue
        conn.commit()
        cursor.close()
        conn.close()
        logging.info(
            f'Successfully stored {stored_count} of {len(prompts)} critic prompts in database'
            )
        return stored_count > 0
    except Exception as e:
        logging.error(f'Error in store_prompts_in_db: {str(e)}')
        logging.error(traceback.format_exc())
        return False


def main():
    start_time = time.time()
    logging.info('Starting create_critic_templates.py script')
    try:
        claude_prompt = create_claude_prompt()
        prompts = query_claude(claude_prompt)
        logging.info(f'Generated {len(prompts)} critic prompt variations')
        if prompts:
            if store_prompts_in_db(prompts):
                logging.info('Successfully stored critic prompts in database')
            else:
                logging.error('Failed to store critic prompts in database')
        else:
            logging.error('No critic prompts generated')
        elapsed_time = time.time() - start_time
        logging.info(f'Script completed in {elapsed_time:.2f} seconds')
    except Exception as e:
        logging.error(f'Script failed with error: {str(e)}')
        logging.error(traceback.format_exc())


if __name__ == '__main__':
    main()
