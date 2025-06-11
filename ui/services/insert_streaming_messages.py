import os
import re
import json
import sys
import argparse
import logging
from pathlib import Path
import shutil
logging.basicConfig(level=logging.INFO, format=
    '%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
SERVICE_PATHS = {'nl_to_sql': 'nl_to_sql_service.py', 'suggestions':
    'suggestions_service.py', 'analysis': 'analysis_service.py'}
RESOURCES_DIR = '../../resources'
MESSAGES_JSON_PATH = os.path.join(RESOURCES_DIR, 'streaming_messages.json')
OUTPUT_DIR = 'modified_services'
DEFAULT_MESSAGES = {'nl_to_sql': {'starting': {'status': 'starting',
    'message': 'Starting SQL generation for your question', 'progress': 0},
    'validating_input': {'status': 'progress', 'message':
    'Validating your input', 'progress': 10}, 'loading_schema': {'status':
    'progress', 'message': 'Loading database schema information',
    'progress': 20}, 'generating_sql': {'status': 'progress', 'message':
    'Generating SQL query from your question', 'progress': 30},
    'model_api_call': {'status': 'progress', 'message':
    'Asking AI to convert your question to SQL', 'progress': 40},
    'sql_generated': {'status': 'progress', 'message':
    'SQL query generated successfully', 'progress': 50}, 'executing_sql': {
    'status': 'progress', 'message': 'Executing SQL query against database',
    'progress': 60}, 'sql_executed': {'status': 'progress', 'message':
    'SQL query executed successfully', 'progress': 70}, 'retry_sql': {
    'status': 'progress', 'message':
    'Refining SQL query for better results', 'progress': 65},
    'processing_results': {'status': 'progress', 'message':
    'Processing query results', 'progress': 80}, 'formatting_answer': {
    'status': 'progress', 'message': 'Formatting answer for display',
    'progress': 90}, 'complete': {'status': 'complete', 'message':
    'Query processing complete', 'progress': 100}, 'error': {'status':
    'error', 'message': 'Error processing your query', 'progress': 100}},
    'suggestions': {'starting': {'status': 'starting', 'message':
    'Starting suggestion generation', 'progress': 0}, 'validating_input': {
    'status': 'progress', 'message': 'Validating your input', 'progress': 
    10}, 'loading_schema': {'status': 'progress', 'message':
    'Loading database schema information', 'progress': 20},
    'checking_existing': {'status': 'progress', 'message':
    'Checking for existing suggestions', 'progress': 30}, 'model_api_call':
    {'status': 'progress', 'message': 'Asking AI to generate suggestions',
    'progress': 40}, 'generating_suggestions': {'status': 'progress',
    'message': 'Generating suggestions for your question', 'progress': 60},
    'processing_suggestions': {'status': 'progress', 'message':
    'Processing generated suggestions', 'progress': 80}, 'complete': {
    'status': 'complete', 'message': 'Suggestion generation complete',
    'progress': 100}, 'error': {'status': 'error', 'message':
    'Error generating suggestions', 'progress': 100}},
    'process_selected_suggestions': {'starting': {'status': 'starting',
    'message': 'Processing your selected suggestions', 'progress': 0},
    'validating_input': {'status': 'progress', 'message':
    'Validating your selections', 'progress': 10}, 'processing_suggestion':
    {'status': 'progress', 'message':
    'Processing suggestion: {suggestion_text}', 'progress': '{dynamic}'},
    'generating_sql': {'status': 'progress', 'message':
    'Generating SQL for suggestion: {suggestion_text}', 'progress':
    '{dynamic}'}, 'executing_sql': {'status': 'progress', 'message':
    'Executing SQL for suggestion: {suggestion_text}', 'progress':
    '{dynamic}'}, 'formatting_answers': {'status': 'progress', 'message':
    'Formatting answers for display', 'progress': 90}, 'complete': {
    'status': 'complete', 'message':
    'All suggestions processed successfully', 'progress': 100}, 'error': {
    'status': 'error', 'message': 'Error processing suggestions',
    'progress': 100}}, 'analysis': {'starting': {'status': 'starting',
    'message': 'Starting comprehensive analysis', 'progress': 0},
    'fetching_data': {'status': 'progress', 'message':
    'Fetching query results for analysis', 'progress': 20},
    'model_api_call': {'status': 'progress', 'message':
    'Asking AI to analyze your data', 'progress': 40},
    'generating_analysis': {'status': 'progress', 'message':
    'Generating detailed analysis of your data', 'progress': 60},
    'comparative_analysis': {'status': 'progress', 'message':
    'Creating comparative analysis of all queries', 'progress': 80},
    'storing_results': {'status': 'progress', 'message':
    'Storing analysis results', 'progress': 90}, 'complete': {'status':
    'complete', 'message': 'Analysis complete', 'progress': 100}, 'error':
    {'status': 'error', 'message': 'Error generating analysis', 'progress':
    100}}}


def ensure_directories():
    os.makedirs(RESOURCES_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def create_messages_json(overwrite=False):
    if os.path.exists(MESSAGES_JSON_PATH) and not overwrite:
        logger.info(
            f'Messages JSON file already exists at {MESSAGES_JSON_PATH}')
        return
    with open(MESSAGES_JSON_PATH, 'w') as f:
        json.dump(DEFAULT_MESSAGES, f, indent=2)
    logger.info(f'Created messages JSON file: {MESSAGES_JSON_PATH}')


def add_import_statement(file_content):
    if 'from services import stream_manager' not in file_content:
        import_lines = re.findall('^import.*$|^from.*import.*$',
            file_content, re.MULTILINE)
        if import_lines:
            last_import = import_lines[-1]
            file_content = file_content.replace(last_import,
                f"""{last_import}
from services import stream_manager""")
        else:
            file_content = (
                f'from services import stream_manager\n\n{file_content}')
    return file_content


def process_nl_to_sql_service(file_content):
    file_content = add_import_statement(file_content)
    pattern = (
        "@bp\\.route\\(\\'\\'.*?\\ndef generate_sql\\(\\):.*?try:.*?data = request\\.json"
        )
    match = re.search(pattern, file_content, re.DOTALL)
    if match:
        insertion = match.group(0) + """
        # Update stream status
        dataset_id = data.get('dataset_id')
        user_id = data.get('user_id')
        if dataset_id and user_id:
            stream_manager.update_stream(user_id, dataset_id, "nl_to_sql", "starting", "Starting SQL generation for your question", 0)"""
        file_content = file_content.replace(match.group(0), insertion)
    pattern = (
        'def generate_sql_with_flash\\(.*?\\):.*?# Call Flash API.*?response_data = call_flash_api'
        )
    match = re.search(pattern, file_content, re.DOTALL)
    if match:
        insertion = match.group(0).replace('# Call Flash API',
            """# Call Flash API
        # Update stream status
        if "user_id" in locals() and "dataset_id" in locals() and user_id and dataset_id:
            stream_manager.update_stream(user_id, dataset_id, "nl_to_sql", "model_api_call", "Asking AI to convert your question to SQL", 40)"""
            )
        file_content = file_content.replace(match.group(0), insertion)
    pattern = (
        '# Extract fields.*?sql = response_data\\.get\\("sql_query", ""\\)')
    match = re.search(pattern, file_content, re.DOTALL)
    if match:
        insertion = match.group(0) + """

        # Update stream status
        if "user_id" in locals() and "dataset_id" in locals() and user_id and dataset_id:
            stream_manager.update_stream(user_id, dataset_id, "nl_to_sql", "sql_generated", "SQL query generated successfully", 50)"""
        file_content = file_content.replace(match.group(0), insertion)
    pattern = (
        '# Execute the SQL.*?execution_result = execute_sql_query\\(sql\\)')
    match = re.search(pattern, file_content, re.DOTALL)
    if match:
        insertion = match.group(0).replace('# Execute the SQL',
            """# Execute the SQL
        # Update stream status
        if "user_id" in locals() and "dataset_id" in locals() and user_id and dataset_id:
            stream_manager.update_stream(user_id, dataset_id, "nl_to_sql", "executing_sql", "Executing SQL query against database", 60)"""
            )
        file_content = file_content.replace(match.group(0), insertion)
    pattern = (
        'execution_result = execute_sql_query\\(sql\\).*?if not execution_result\\.get\\("success"\\):'
        )
    match = re.search(pattern, file_content, re.DOTALL)
    if match:
        insertion = match.group(0).replace(
            'if not execution_result.get("success"):',
            """# Update stream status
        if "user_id" in locals() and "dataset_id" in locals() and user_id and dataset_id:
            stream_manager.update_stream(user_id, dataset_id, "nl_to_sql", "sql_executed", "SQL executed, processing results", 70)

        if not execution_result.get("success"):"""
            )
        file_content = file_content.replace(match.group(0), insertion)
    pattern = (
        '# Call Flash API for retry.*?sql, thought_process, explanation = generate_sql_with_flash'
        )
    match = re.search(pattern, file_content, re.DOTALL)
    if match:
        insertion = match.group(0).replace('# Call Flash API for retry',
            """# Call Flash API for retry
            # Update stream status
            if "user_id" in locals() and "dataset_id" in locals() and user_id and dataset_id:
                stream_manager.update_stream(user_id, dataset_id, "nl_to_sql", "retry_sql", "Refining SQL query for better results", 65)"""
            )
        file_content = file_content.replace(match.group(0), insertion)
    pattern = (
        '# Format answer.*?answer = format_answer_from_results\\(results\\)')
    match = re.search(pattern, file_content, re.DOTALL)
    if match:
        insertion = match.group(0).replace('# Format answer',
            """# Format answer
        # Update stream status
        if "user_id" in locals() and "dataset_id" in locals() and user_id and dataset_id:
            stream_manager.update_stream(user_id, dataset_id, "nl_to_sql", "formatting_answer", "Formatting answer for display", 90)"""
            )
        file_content = file_content.replace(match.group(0), insertion)
    pattern = '# Return response.*?return jsonify\\(\\{'
    match = re.search(pattern, file_content, re.DOTALL)
    if match:
        insertion = match.group(0).replace('# Return response',
            """# Update stream status
        if "user_id" in locals() and "dataset_id" in locals() and user_id and dataset_id:
            stream_manager.update_stream(user_id, dataset_id, "nl_to_sql", "complete", "Query processing complete", 100)

        # Return response"""
            )
        file_content = file_content.replace(match.group(0), insertion)
    pattern = (
        'except Exception as e:.*?return jsonify\\(\\{"error": str\\(e\\)\\}\\)'
        )
    match = re.search(pattern, file_content, re.DOTALL)
    if match:
        insertion = match.group(0).replace('return jsonify({"error": str(e)})',
            """# Update stream status with error
        if "user_id" in locals() and "dataset_id" in locals() and user_id and dataset_id:
            stream_manager.update_stream(user_id, dataset_id, "nl_to_sql", "error", f"Error: {str(e)}", 100)
        return jsonify({"error": str(e)})"""
            )
        file_content = file_content.replace(match.group(0), insertion)
    return file_content


def process_suggestions_service(file_content):
    file_content = add_import_statement(file_content)
    pattern = (
        "@bp\\.route\\(\\'\\'.*?\\ndef get_suggestions\\(\\):.*?try:.*?data = request\\.json"
        )
    match = re.search(pattern, file_content, re.DOTALL)
    if match:
        insertion = match.group(0) + """
        # Update stream status
        dataset_id = data.get('dataset_id')
        user_id = data.get('user_id')
        if dataset_id and user_id:
            stream_manager.update_stream(user_id, dataset_id, "suggestions", "starting", "Starting suggestion generation", 0)"""
        file_content = file_content.replace(match.group(0), insertion)
    pattern = (
        'def call_flash_api\\(prompt, response_schema, max_tokens=.*?\\):.*?logger.info\\("Calling Flash \\(Gemini\\) API"\\)'
        )
    match = re.search(pattern, file_content, re.DOTALL)
    if match:
        insertion = match.group(0) + """
        # Update stream status if user_id and dataset_id are available
        if "user_id" in globals() and "dataset_id" in globals() and user_id and dataset_id:
            stream_manager.update_stream(user_id, dataset_id, "suggestions", "model_api_call", "Asking AI to generate suggestions", 40)"""
        file_content = file_content.replace(match.group(0), insertion)
    pattern = (
        'suggestions_data = generate_suggestions.*?if not suggestions_data:')
    match = re.search(pattern, file_content, re.DOTALL)
    if match:
        insertion = match.group(0).replace('if not suggestions_data:',
            """# Update stream status
        if "user_id" in locals() and "dataset_id" in locals() and user_id and dataset_id:
            stream_manager.update_stream(user_id, dataset_id, "suggestions", "processing_suggestions", "Processing generated suggestions", 70)

        if not suggestions_data:"""
            )
        file_content = file_content.replace(match.group(0), insertion)
    pattern = '# Return suggestions to client.*?return jsonify\\(\\{'
    match = re.search(pattern, file_content, re.DOTALL)
    if match:
        insertion = match.group(0).replace('# Return suggestions to client',
            """# Update stream status
        if "user_id" in locals() and "dataset_id" in locals() and user_id and dataset_id:
            stream_manager.update_stream(user_id, dataset_id, "suggestions", "complete", "Suggestion generation complete", 100)

        # Return suggestions to client"""
            )
        file_content = file_content.replace(match.group(0), insertion)
    pattern = (
        "@bp\\.route\\(\\'/process-selected\\'.*?\\ndef process_selected_suggestions\\(\\):.*?try:.*?data = request\\.json"
        )
    match = re.search(pattern, file_content, re.DOTALL)
    if match:
        insertion = match.group(0) + """
        # Update stream status
        dataset_id = data.get('dataset_id')
        user_id = data.get('user_id')
        selected_suggestions = data.get('selected_suggestions', [])
        if dataset_id and user_id:
            stream_manager.update_stream(user_id, dataset_id, "process_selected_suggestions", "starting", "Processing your selected suggestions", 0)"""
        file_content = file_content.replace(match.group(0), insertion)
    pattern = (
        '# Process each suggestion.*?for suggestion in selected_suggestions:')
    match = re.search(pattern, file_content, re.DOTALL)
    if match:
        insertion = match.group(0) + """
            # Calculate progress based on number of suggestions
            total_suggestions = len(selected_suggestions)
            suggestion_progress_increment = 70 / max(total_suggestions, 1)"""
        file_content = file_content.replace(match.group(0), insertion)
    pattern = (
        "for suggestion in selected_suggestions:.*?question = suggestion\\.get\\(\\'question\\', \\'\\'\\)"
        )
    match = re.search(pattern, file_content, re.DOTALL)
    if match:
        insertion = match.group(0) + """

            # Update progress for this suggestion
            current_index = selected_suggestions.index(suggestion)
            progress = 20 + (current_index * suggestion_progress_increment)
            progress_message = f"Processing suggestion {current_index + 1} of {total_suggestions}"
            if user_id and dataset_id:
                stream_manager.update_stream(user_id, dataset_id, "process_selected_suggestions", "progress", progress_message, int(progress))"""
        file_content = file_content.replace(match.group(0), insertion)
    pattern = '# Return response.*?return jsonify\\(\\{.*?"success": True'
    match = re.search(pattern, file_content, re.DOTALL)
    if match:
        insertion = match.group(0).replace('# Return response',
            """# Update stream status
        if "user_id" in locals() and "dataset_id" in locals() and user_id and dataset_id:
            stream_manager.update_stream(user_id, dataset_id, "process_selected_suggestions", "complete", "All suggestions processed successfully", 100)

        # Return response"""
            )
        file_content = file_content.replace(match.group(0), insertion)
    return file_content


def process_analysis_service(file_content):
    file_content = add_import_statement(file_content)
    pattern = (
        "@bp\\.route\\(\\'/\\<dataset_id\\>\\'.*?\\ndef get_analysis\\(dataset_id\\):.*?try:"
        )
    match = re.search(pattern, file_content, re.DOTALL)
    if match:
        insertion = match.group(0) + """
        # Get user_id from session
        user_id = session.get('user_id')
        if user_id:
            stream_manager.update_stream(user_id, dataset_id, "analysis", "starting", "Starting comprehensive analysis", 0)"""
        file_content = file_content.replace(match.group(0), insertion)
    pattern = (
        '# If either analysis is missing, generate new analysis.*?# Generate new analysis'
        )
    match = re.search(pattern, file_content, re.DOTALL)
    if match:
        insertion = match.group(0).replace('# Generate new analysis',
            """# Update stream status
            if "user_id" in locals() and user_id:
                stream_manager.update_stream(user_id, dataset_id, "analysis", "fetching_data", "Fetching query results for analysis", 20)

            # Generate new analysis"""
            )
        file_content = file_content.replace(match.group(0), insertion)
    pattern = '# Call Gemini API.*?response_text = call_gemini_api\\(prompt\\)'
    match = re.search(pattern, file_content, re.DOTALL)
    if match:
        insertion = match.group(0).replace('# Call Gemini API',
            """# Update stream status
        if "user_id" in locals() and user_id:
            stream_manager.update_stream(user_id, dataset_id, "analysis", "model_api_call", "Asking AI to analyze your data", 40)

        # Call Gemini API"""
            )
        file_content = file_content.replace(match.group(0), insertion)
    pattern = (
        'response_text = call_gemini_api\\(prompt\\).*?if not response_text:')
    match = re.search(pattern, file_content, re.DOTALL)
    if match:
        insertion = match.group(0).replace('if not response_text:',
            """# Update stream status
        if "user_id" in locals() and user_id:
            stream_manager.update_stream(user_id, dataset_id, "analysis", "generating_analysis", "Generating detailed analysis of your data", 60)

        if not response_text:"""
            )
        file_content = file_content.replace(match.group(0), insertion)
    pattern = (
        '# Parse JSON response.*?try:.*?analysis_data = json\\.loads\\(response_text\\)'
        )
    match = re.search(pattern, file_content, re.DOTALL)
    if match:
        insertion = match.group(0).replace(
            'analysis_data = json.loads(response_text)',
            """analysis_data = json.loads(response_text)

            # Update stream status
            if "user_id" in locals() and user_id:
                stream_manager.update_stream(user_id, dataset_id, "analysis", "comparative_analysis", "Creating comparative analysis of all queries", 80)"""
            )
        file_content = file_content.replace(match.group(0), insertion)
    pattern = (
        '# Store the analysis for each model.*?for model, queries in queries_by_model\\.items\\(\\):'
        )
    match = re.search(pattern, file_content, re.DOTALL)
    if match:
        insertion = match.group(0).replace(
            'for model, queries in queries_by_model.items():',
            """# Update stream status
            if "user_id" in locals() and user_id:
                stream_manager.update_stream(user_id, dataset_id, "analysis", "storing_results", "Storing analysis results", 90)

            for model, queries in queries_by_model.items():"""
            )
        file_content = file_content.replace(match.group(0), insertion)
    pattern = '# Return the analysis data.*?return jsonify\\(\\{'
    match = re.search(pattern, file_content, re.DOTALL)
    if match:
        insertion = match.group(0).replace('# Return the analysis data',
            """# Update stream status
        if "user_id" in locals() and user_id:
            stream_manager.update_stream(user_id, dataset_id, "analysis", "complete", "Analysis complete", 100)

        # Return the analysis data"""
            )
        file_content = file_content.replace(match.group(0), insertion)
    pattern = (
        "except Exception as e:.*?return jsonify\\(\\{.*?\\'success\\': False")
    match = re.search(pattern, file_content, re.DOTALL)
    if match:
        insertion = match.group(0).replace('return jsonify({',
            """# Update stream status with error
        if "user_id" in locals() and user_id:
            stream_manager.update_stream(user_id, dataset_id, "analysis", "error", f"Error: {str(e)}", 100)
        return jsonify({"""
            )
        file_content = file_content.replace(match.group(0), insertion)
    return file_content


def process_file(file_path, processor_func, in_place=False, backup=False):
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        updated_content = processor_func(content)
        if backup:
            backup_path = f'{file_path}.bak'
            with open(backup_path, 'w') as f:
                f.write(content)
            logger.info(f'Created backup: {backup_path}')
        if in_place:
            output_path = file_path
        else:
            output_path = os.path.join(OUTPUT_DIR, os.path.basename(file_path))
        with open(output_path, 'w') as f:
            f.write(updated_content)
        logger.info(f'Updated {file_path} -> {output_path}')
        return True
    except Exception as e:
        logger.error(f'Error processing {file_path}: {str(e)}')
        return False


def main():
    parser = argparse.ArgumentParser(description=
        'Insert streaming updates into service files')
    parser.add_argument('--in-place', action='store_true', help=
        'Modify files in-place instead of creating copies')
    parser.add_argument('--backup', action='store_true', help=
        'Create backup of original files')
    parser.add_argument('--overwrite-messages', action='store_true', help=
        'Overwrite existing messages JSON file')
    args = parser.parse_args()
    ensure_directories()
    create_messages_json(args.overwrite_messages)
    processors = {'nl_to_sql': process_nl_to_sql_service, 'suggestions':
        process_suggestions_service, 'analysis': process_analysis_service}
    for service_name, file_name in SERVICE_PATHS.items():
        if os.path.exists(file_name):
            processor = processors.get(service_name)
            if processor:
                logger.info(f'Processing {file_name}...')
                process_file(file_name, processor, args.in_place, args.backup)
            else:
                logger.warning(f'No processor defined for {service_name}')
        else:
            logger.warning(f'File not found: {file_name}')
    logger.info('Streaming updates have been added to the service files.')
    logger.info(f'Messages JSON file: {MESSAGES_JSON_PATH}')
    logger.info(
        'You can modify the streaming messages by editing the JSON file.')


if __name__ == '__main__':
    main()
