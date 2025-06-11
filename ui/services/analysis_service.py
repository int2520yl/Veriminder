from flask import Blueprint, request, jsonify, current_app, session
import json
import logging
import mysql.connector
import os
import traceback
from google import genai
from google.genai import types
from datetime import datetime
from . import stream_manager
os.makedirs('logs', exist_ok=True)
logging.basicConfig(filename='logs/analysis_service.log', level=logging.
    INFO, format=
    '%(asctime)s - %(levelname)s - %(pathname)s:%(lineno)d - %(message)s')
logger = logging.getLogger(__name__)
bp = Blueprint('analysis', __name__, url_prefix='/api/analysis')
DB_CONFIG = {
    'host': 'YOUR_DATABASE_HOST',
    'port': 'YOUR_DATABASE_POST',
    'user': 'YOUR_DATABASE_USER',
    'password': 'YOUR_DATABASE_PASSWORD',
    'database': 'YOUR_DATABASE_NAME'
}

MODEL = 'gemini-2.0-flash-001'
SCHEMA_FILE_PATH = '../../data/BIRD_table_schema_info.json'
EVIDENCE_FILE_PATH = '../../data/all_evidence.json'
genai_client = genai.Client(project="your-gcp-project-id")


def get_db_connection():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except mysql.connector.Error as e:
        logger.error(f'Database connection error: {str(e)}')
        raise


def load_schema_data():
    try:
        if os.path.exists(SCHEMA_FILE_PATH):
            with open(SCHEMA_FILE_PATH, 'r') as f:
                return json.load(f)
        else:
            logger.warning(f'Schema file not found: {SCHEMA_FILE_PATH}')
            return None
    except Exception as e:
        logger.error(f'Error loading schema data: {str(e)}')
        return None


def load_evidence_data():
    try:
        if os.path.exists(EVIDENCE_FILE_PATH):
            with open(EVIDENCE_FILE_PATH, 'r') as f:
                return json.load(f)
        else:
            logger.warning(f'Evidence file not found: {EVIDENCE_FILE_PATH}')
            return None
    except Exception as e:
        logger.error(f'Error loading evidence data: {str(e)}')
        return None


def call_gemini_api(prompt):
    try:
        logger.info('Calling Gemini Flash API')
        start_time = datetime.now()
        contents = [types.Content(role='user', parts=[types.Part.from_text(
            text=prompt)])]
        generate_content_config = types.GenerateContentConfig(temperature=0,
            top_p=0.95, max_output_tokens=8192, response_modalities=['TEXT'
            ], safety_settings=[types.SafetySetting(category=
            'HARM_CATEGORY_HATE_SPEECH', threshold='OFF'), types.
            SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT',
            threshold='OFF'), types.SafetySetting(category=
            'HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='OFF'), types.
            SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold=
            'OFF')], response_mime_type='application/json', response_schema
            ={'type': 'OBJECT', 'properties': {'question_to_sql': {'type':
            'OBJECT', 'properties': {'summary': {'type': 'STRING'},
            'detailed_analysis': {'type': 'STRING'}}, 'required': [
            'summary', 'detailed_analysis']}, 'baqr': {'type': 'OBJECT',
            'properties': {'summary': {'type': 'STRING'},
            'detailed_analysis': {'type': 'STRING'}}, 'required': [
            'summary', 'detailed_analysis']}}, 'required': [
            'question_to_sql', 'baqr']})
        response = genai_client.models.generate_content(model=MODEL,
            contents=contents, config=generate_content_config)
        end_time = datetime.now()
        execution_time = (end_time - start_time).total_seconds()
        logger.info(
            f'Gemini API response received in {execution_time:.2f} seconds')
        if hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'content') and candidate.content:
                parts = candidate.content.parts
                if parts:
                    response_text = parts[0].text
                    logger.info(
                        f'Response length: {len(response_text)} characters')
                    return response_text
        logger.error('No valid response received from Gemini API')
        return None
    except Exception as e:
        logger.error(f'Error calling Gemini API: {str(e)}')
        logger.error(traceback.format_exc())
        return None


def fetch_analysis(cursor, dataset_id, model_type):
    try:
        cursor.execute(
            'SELECT * FROM summary_analysis WHERE dataset_id = %s AND evaluation_model = %s'
            , (dataset_id, model_type))
        result = cursor.fetchone()
        if not result:
            logger.warning(
                f'No analysis found for dataset_id {dataset_id} and model {model_type}'
                )
            return None
        summary_json = result.get('summary')
        if not summary_json:
            logger.warning(
                f'No summary field in analysis for dataset_id {dataset_id} and model {model_type}'
                )
            return None
        if isinstance(summary_json, str):
            try:
                summary_data = json.loads(summary_json)
            except json.JSONDecodeError:
                logger.error(
                    f'Failed to parse summary JSON for dataset_id {dataset_id} and model {model_type}'
                    )
                return None
        else:
            summary_data = summary_json
        return summary_data
    except Exception as e:
        logger.error(f'Error in fetch_analysis: {str(e)}')
        raise


def get_successful_queries_by_model(conn, dataset_id, query_models):
    cursor = conn.cursor(dictionary=True)
    queries_by_model = {}
    all_previous_queries = []
    for i, query_model in enumerate(query_models):
        query = """
        SELECT id, NL_question, execution_details 
        FROM query
        WHERE dataset_id = %s
        AND query_model = %s
        AND (sql_generation_status = 'a1_done' OR sql_generation_status = 'a2_done')
        AND execution_status = 'success'
        AND status = 'active'
        ORDER BY model_query_sequence_index ASC
        """
        cursor.execute(query, (dataset_id, query_model))
        model_queries = cursor.fetchall()
        current_model_queries = []
        if model_queries:
            for query in model_queries:
                execution_details = json.loads(query['execution_details']
                    ) if query['execution_details'] else {}
                query_data = {'id': query['id'], 'NL_question': query[
                    'NL_question'], 'result_rows': execution_details.get(
                    'result_rows', [])}
                current_model_queries.append(query_data)
            logger.info(
                f'Found {len(model_queries)} successful queries for dataset_id {dataset_id}, model {query_model}'
                )
        if i == 0:
            queries_by_model[query_model] = current_model_queries
            all_previous_queries = current_model_queries.copy()
        else:
            queries_by_model[query_model
                ] = all_previous_queries + current_model_queries
            all_previous_queries = queries_by_model[query_model].copy()
    cursor.close()
    return queries_by_model


def get_decision_text(conn, dataset_id):
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT decision FROM dataset WHERE id = %s', (dataset_id,))
    result = cursor.fetchone()
    cursor.close()
    if result and result.get('decision'):
        try:
            decision_json = json.loads(result['decision'])
            return decision_json.get('text', '')
        except (json.JSONDecodeError, TypeError):
            return ''
    return ''


def build_gemini_prompt(decision_text, queries_by_model):
    schema_data = load_schema_data()
    evidence_data = load_evidence_data()
    prompt = f"""
You are tasked with analyzing the results of database queries in relation to a decision-making scenario. 

The decision to analyze is:
"{decision_text}"

I will provide you with executed queries and their results, organized by query model type. Your task is to provide an analysis of what insights these query results offer in relation to the decision, including any limitations or potential issues.

NOTE: For queries that return lists, only up to 10 rows are fetched. Keep this in mind when summarizing and analyzing the data.
"""
    if schema_data:
        prompt += """
=== DATABASE SCHEMA INFORMATION ===
The following information describes the database structure that was available to the models:
"""
        prompt += json.dumps(schema_data, indent=2)
        prompt += '\n\n'
    if evidence_data:
        prompt += """
=== RELEVANT EVIDENCE AND CONTEXT ===
The following evidence provides additional context for analyzing the queries:
"""
        prompt += json.dumps(evidence_data, indent=2)
        prompt += '\n\n'
    for model, queries in queries_by_model.items():
        prompt += f"""
=== QUERY MODEL: {model.upper()} ===
The following {len(queries)} queries were executed:

"""
        for i, query in enumerate(queries, 1):
            nl_question = query.get('NL_question', '')
            result_data = json.dumps(query.get('result_rows', []), indent=2)
            prompt += f"""
Query
Natural Language Question: {nl_question}
Results: {result_data}

"""
    prompt += """
    IMPORTANT: 
    1. Base your analysis STRICTLY on the information provided in the queries and results.
    2. CRITICAL: Your response text MUST NOT contain any model names like "BAQR" or "question_to_sql". DO NOT start sentences with phrases like "The BAQR model" or "The question_to_sql model". Instead, refer to "the model" or use passive voice.
    3. Do not introduce external information not present in the query results.
    4. Provide your response in a JSON object with sections for each model.
    5. Your analysis should be objective and focused on what the data actually shows.
    6. For each model, provide a one-sentence summary and a two-sentence detailed analysis.
    7. If there are no queries for a particular model, include that model with empty responses.
    """
    return prompt


def generate_analysis(conn, dataset_id, user_id):
    try:
        decision_text = get_decision_text(conn, dataset_id)
        if not decision_text:
            logger.error(f'No decision text found for dataset_id {dataset_id}')
            return None
        queries_by_model = get_successful_queries_by_model(conn, dataset_id,
            ['question_to_sql', 'baqr'])
        if not queries_by_model:
            logger.error(
                f'No successful queries found for dataset_id {dataset_id}')
            return None
        prompt = build_gemini_prompt(decision_text, queries_by_model)
        if user_id and dataset_id:
            stream_manager.update_stream(user_id, dataset_id, 'analysis',
                'model_api_call', 'Asking AI to analyze your data', 40)
        response_text = call_gemini_api(prompt)
        if user_id and dataset_id:
            stream_manager.update_stream(user_id, dataset_id, 'analysis',
                'generating_analysis',
                'Generating detailed analysis of your data', 60)
        if not response_text:
            logger.error(
                f'Failed to get response from Gemini API for dataset_id {dataset_id}'
                )
            return None
        try:
            analysis_data = json.loads(response_text)
            for model_name in analysis_data:
                if isinstance(analysis_data[model_name], dict):
                    for field in ['summary', 'detailed_analysis']:
                        if field in analysis_data[model_name]:
                            text = analysis_data[model_name][field]
                            text = text.replace('The BAQR model', 'The model')
                            text = text.replace('The question_to_sql model',
                                'The model')
                            text = text.replace('BAQR model', 'model')
                            text = text.replace('question_to_sql model',
                                'model')
                            analysis_data[model_name][field] = text
            if user_id and dataset_id:
                stream_manager.update_stream(user_id, dataset_id,
                    'analysis', 'comparative_analysis',
                    'Creating comparative analysis of all queries', 80)
            if user_id and dataset_id:
                stream_manager.update_stream(user_id, dataset_id,
                    'analysis', 'storing_results',
                    'Storing analysis results', 90)
            for model, queries in queries_by_model.items():
                if model in analysis_data:
                    store_analysis(conn, dataset_id, model, decision_text,
                        queries, analysis_data[model], response_text)
            return analysis_data
        except json.JSONDecodeError as e:
            logger.error(f'Failed to parse JSON from Gemini response: {str(e)}'
                )
            logger.error(f'Raw response: {response_text[:1000]}...')
            return None
    except Exception as e:
        logger.error(f'Error generating analysis: {str(e)}')
        logger.error(traceback.format_exc())
        return None


def store_analysis(conn, dataset_id, model, decision_text, queries,
    analysis_data, raw_response):
    try:
        cursor = conn.cursor()
        query_id_details = {'query_ids': [q.get('id') for q in queries],
            'total_queries': len(queries)}
        query_execution_details = {'queries': [{'id': q.get('id'),
            'NL_question': q.get('NL_question'), 'result_rows': q.get(
            'result_rows', [])} for q in queries]}
        prompt_details = {'decision_text': decision_text, 'query_count':
            len(queries), 'raw_response': raw_response[:1000] if
            raw_response else ''}
        cursor.execute(
            'SELECT id FROM summary_analysis WHERE dataset_id = %s AND evaluation_model = %s'
            , (dataset_id, model))
        existing = cursor.fetchone()
        if existing:
            update_query = """
            UPDATE summary_analysis
            SET prompt_details = %s,
                summary = %s,
                query_id_details = %s,
                query_execution_details = %s,
                prompt_status = %s,
                status = %s
            WHERE dataset_id = %s AND evaluation_model = %s
            """
            cursor.execute(update_query, (json.dumps(prompt_details), json.
                dumps(analysis_data), json.dumps(query_id_details), json.
                dumps(query_execution_details), 'success', 'active',
                dataset_id, model))
            logger.info(
                f'Updated existing summary analysis for dataset {dataset_id}, model {model}'
                )
        else:
            insert_query = """
            INSERT INTO summary_analysis
            (dataset_id, evaluation_model, prompt_details, summary, query_id_details, 
            query_execution_details, prompt_status, status, version)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(insert_query, (dataset_id, model, json.dumps(
                prompt_details), json.dumps(analysis_data), json.dumps(
                query_id_details), json.dumps(query_execution_details),
                'success', 'active', 1))
            logger.info(
                f'Inserted new summary analysis for dataset {dataset_id}, model {model}'
                )
        conn.commit()
        cursor.close()
        return True
    except Exception as e:
        logger.error(f'Error storing analysis: {str(e)}')
        logger.error(traceback.format_exc())
        conn.rollback()
        return False


@bp.route('/<dataset_id>', methods=['GET'])
def get_analysis(dataset_id):
    try:
        user_id = session.get('user_id')
        if user_id:
            stream_manager.update_stream(user_id, dataset_id, 'analysis',
                'starting', 'Starting comprehensive analysis', 0)
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        logger.info(f'Fetching analysis for dataset_id: {dataset_id}')
        initial_analysis = fetch_analysis(cursor, dataset_id, 'question_to_sql'
            )
        comprehensive_analysis = fetch_analysis(cursor, dataset_id, 'baqr')
        cursor.close()
        if not initial_analysis or not comprehensive_analysis:
            logger.info(
                f'Analysis missing for dataset_id {dataset_id}. Generating new analysis.'
                )
            if user_id and dataset_id:
                stream_manager.update_stream(user_id, dataset_id,
                    'analysis', 'fetching_data',
                    'Fetching query results for analysis', 20)
            analysis_data = generate_analysis(conn, dataset_id, user_id)
            if analysis_data:
                initial_analysis = analysis_data.get('question_to_sql')
                comprehensive_analysis = analysis_data.get('baqr')
            else:
                logger.error(
                    f'Failed to generate analysis for dataset_id {dataset_id}')
        conn.close()
        if user_id and dataset_id:
            stream_manager.update_stream(user_id, dataset_id, 'analysis',
                'complete', 'Analysis complete', 100)
        return jsonify({'success': True, 'initialAnalysis':
            initial_analysis, 'comprehensiveAnalysis': comprehensive_analysis})
    except Exception as e:
        logger.error(f'Error fetching analysis: {str(e)}')
        logger.error(traceback.format_exc())
        if user_id and dataset_id:
            stream_manager.update_stream(user_id, dataset_id, 'analysis',
                'error', f'Error: {str(e)}', 100)
        return jsonify({'success': False, 'message':
            f'Error retrieving analysis: {str(e)}'}), 500
