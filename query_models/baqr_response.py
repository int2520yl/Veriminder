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
logging.basicConfig(filename='logs/baqr_question_generator.log', level=
    logging.INFO, format=
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
STATS_FILE_PATH = '../data/compact_dataset_stats.json'
PILLAR_DIR = '../resources/question_guide_pillars/'
TOULMIN_FILE_PATH = os.path.join(PILLAR_DIR, 'toulmin_argument_structure.json')
DATASET_SCHEMA_FILE_PATH = os.path.join(PILLAR_DIR,
    'dataset_schema_based_patterns.json')
VULNERABILITY_FILE_PATH = os.path.join(PILLAR_DIR,
    'vulnerability_semantic_frames.json')
COUNTERARGUMENT_FILE_PATH = os.path.join(PILLAR_DIR,
    'preemptive-counterargument_pattern.json')
TEST_MODE = False
BATCH_SIZE = 3


def load_files():
    try:
        with open(EVIDENCE_FILE_PATH, 'r') as f:
            evidence_data = json.load(f)
        with open(SCHEMA_FILE_PATH, 'r') as f:
            schema_data = json.load(f)
        with open(STATS_FILE_PATH, 'r') as f:
            stats_data = json.load(f)
        pillar_files = {'toulmin': TOULMIN_FILE_PATH, 'dataset_schema':
            DATASET_SCHEMA_FILE_PATH, 'vulnerability':
            VULNERABILITY_FILE_PATH, 'counterargument':
            COUNTERARGUMENT_FILE_PATH}
        pillar_data = {}
        for key, path in pillar_files.items():
            if not os.path.exists(path):
                error_msg = f'Required pillar file not found: {path}'
                logging.error(error_msg)
                raise FileNotFoundError(error_msg)
            with open(path, 'r') as f:
                pillar_data[key] = json.load(f)
        return evidence_data, schema_data, stats_data, pillar_data
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
            "SELECT COUNT(*) as count FROM dataset WHERE baqr_status = 'processing'"
            )
        result = cursor.fetchone()
        if result['count'] > 0:
            logging.error(
                "Found records with 'processing' status. Please check for failures in previous runs."
                )
            raise Exception("Records with 'processing' status found. Exiting.")
        cursor.execute(
            "SELECT id, question_id_from_BIRD, question, decision FROM dataset WHERE baqr_status = 'ready' LIMIT %s"
            , (limit,))
        records = cursor.fetchall()
        if records:
            ids = [record['id'] for record in records]
            placeholders = ', '.join(['%s'] * len(ids))
            cursor.execute(
                f"UPDATE dataset SET baqr_status = 'processing' WHERE id IN ({placeholders})"
                , ids)
            conn.commit()
        cursor.close()
        return records
    except Exception as e:
        logging.error(f'Error getting dataset records: {str(e)}')
        raise


def prepare_prompt(records, evidence_data, schema_data, stats_data, pillar_data
    ):
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
    vulnerability_data = pillar_data.get('vulnerability', {})
    vulnerability_categories = []
    if 'categories' in vulnerability_data:
        for category in vulnerability_data.get('categories', []):
            item_details = []
            for item in category.get('items', []):
                item_details.append({'name': item.get('item_name', ''),
                    'id': item.get('vulnerability_id', 0), 'description':
                    item.get('item_description', '')})
            vulnerability_categories.append({'name': category.get(
                'category_name', ''), 'description': category.get(
                'category_description', ''), 'items': item_details})
    toulmin_data = pillar_data.get('toulmin', {})
    toulmin_components = []
    if 'categories' in toulmin_data:
        for category in toulmin_data.get('categories', []):
            if category.get('category_name') == 'Argument Components':
                for item in category.get('items', []):
                    sub_items = []
                    for sub_item in item.get('sub_items', []):
                        sub_items.append({'name': sub_item.get(
                            'aspect_name', ''), 'description': sub_item.get
                            ('description', '')})
                    toulmin_components.append({'name': item.get('item_name',
                        ''), 'description': item.get('item_description', ''
                        ), 'aspects': sub_items})
    dataset_schema_data = pillar_data.get('dataset_schema', {})
    schema_categories = []
    if 'categories' in dataset_schema_data:
        for category in dataset_schema_data.get('categories', []):
            item_details = []
            for item in category.get('items', []):
                item_details.append({'name': item.get('item_name', ''),
                    'description': item.get('item_description', '')})
            schema_categories.append({'name': category.get('category_name',
                ''), 'description': category.get('category_description', ''
                ), 'items': item_details})
    counterargument_data = pillar_data.get('counterargument', {})
    counterargument_categories = []
    if 'categories' in counterargument_data:
        for category in counterargument_data.get('categories', []):
            item_details = []
            for item in category.get('items', []):
                item_details.append({'name': item.get('item_name', ''),
                    'description': item.get('item_description', '')})
            counterargument_categories.append({'name': category.get(
                'category_name', ''), 'description': category.get(
                'category_description', ''), 'items': item_details})
    relevant_tables = set()
    for entry in dataset_entries:
        decision_text = entry['decision'].lower()
        question_text = entry['question'].lower()
        for table_name in stats_data['tables'].keys():
            if table_name.lower() in decision_text or table_name.lower(
                ) in question_text:
                relevant_tables.add(table_name)
    relevant_stats = {'tables': {}, 'column_groups': {}}
    for table_name in relevant_tables:
        if table_name in stats_data['tables']:
            relevant_stats['tables'][table_name] = stats_data['tables'][
                table_name]
    for group_type, columns in stats_data['column_groups'].items():
        relevant_columns = []
        for column in columns:
            table_name = column.split('.')[0]
            if table_name in relevant_tables:
                relevant_columns.append(column)
        if relevant_columns:
            relevant_stats['column_groups'][group_type] = relevant_columns
    prompt = f"""You are a data science expert specialized in generating precise, insightful questions that lead to robust data-driven decisions. Your goal is to generate questions that result in "hard-to-vary" explanations - explanations that are tightly constrained by data and resist arbitrary modification. All questions must be directly answerable using SQL queries against the provided database schema.


A "hard-to-vary" explanation has these essential characteristics:
- **Data-Constrained:** Each component relies on specific, verifiable data points from the available database.
- **Non-Arbitrary:** Components cannot be easily changed without invalidating the explanation.
- **Falsifiable:** The explanation can be disproven by specific data conditions.
- **Bias-Aware:** It proactively addresses potential cognitive biases and counterarguments.
- **Data-Answerable:** All components can be directly verified through SQL queries against the provided database.

**Decision**: Allocate additional food program funding to high-need schools

**Hard-to-vary explanation**: "Schools with free meal eligibility rates above 75% and enrollment over 500 students should receive priority funding because they serve the largest number of food-insecure children. This explanation is hard-to-vary because changing either the eligibility threshold or minimum enrollment would fundamentally alter the targeting rationale. It's falsifiable - data could show these schools already receive adequate funding."

**Decision**: Allocate additional food program funding to high-need schools

**Explanation**: "Schools with high poverty rates should get more funding because they need it more."

This is easy to vary - "high poverty" is undefined, and "need it more" is subjective. It lacks data constraints and isn't falsifiable.

For each decision scenario, generate:
1. One direct primary question that precisely addresses the core decision need
2. Only about 5 high-impact refinement questions that significantly enhance decision quality

Each question MUST be directly answerable using SQL queries against the provided database schema. Do not reference external knowledge or data not present in the schema.

{json.dumps(dataset_entries, indent=2)}

{json.dumps(schema_data, indent=2)}

This section provides detailed statistical information about the datasets, including record counts, data distributions, and column properties:
{json.dumps(relevant_stats, indent=2)}

{json.dumps(all_relevant_evidence, indent=2)}

Follow this sequential pipeline to generate questions that are directly answerable via SQL:

1.1 Identify the core decision being made:
   - What specific action needs to be taken?
   - What alternatives are being considered?
   - What resources are being allocated?

1.2 Determine critical decision criteria:
   - What quantifiable metrics would indicate success?
   - What thresholds or benchmarks are relevant?
   - What specific database columns contain these metrics?

1.3 Identify key uncertainties:
   - What information gaps create the most risk?
   - Which assumptions, if wrong, would most damage the decision quality?
   - What SQL queries could test these assumptions?

Identify only the 1-2 most critical cognitive biases likely to affect this specific decision:
{json.dumps(vulnerability_categories, indent=2)}

2.1 For each identified critical bias:
   - Explain exactly how this bias threatens this specific decision
   - Detail what data pattern would indicate this bias is present
   - Formulate a precise SQL-answerable question that directly exposes or mitigates this bias
   - Specify how answering this question would make the decision more robust

2.2 Example SQL-answerable bias-mitigating questions:
   - For confirmation bias: "What percentage of cases in the database contradict our hypothesis that high values of [column X] correlate with high values of [column Y]?"
   - For availability bias: "Beyond the most frequently mentioned factors, which other columns in the database show statistical correlation with [outcome column]?"
   - For base rate neglect: "What is the actual distribution of [column Z] across all records in the database, not just in the filtered subset?"

Identify only the most decision-relevant data patterns:
{json.dumps(schema_categories, indent=2)}

3.1 Map critical decision factors to specific database elements:
   - Identify the exact tables containing decision-relevant data
   - List the precise columns needed for analysis
   - Determine join conditions required to connect relevant data

3.2 Assess data quality for decision-critical fields:
   - For columns flagged as high_null_numeric: "What percentage of records have NULL values in [column], and how would results change if we used [specific SQL imputation method]?"
   - For imbalanced columns: "How does the distribution of [column] affect our analysis when we GROUP BY this column in SQL?"
   - For skewed distributions: "What is the difference between the mean and median of [column] when calculated using SQL aggregation functions?"

3.3 Validate data sufficiency with SQL-focused questions:
   - "How many records meet all our filtering criteria in the SQL query?"
   - "What percentage of the total dataset remains after applying all WHERE conditions?"
   - "Do we have sufficient data in each group when we segment by [column] in our GROUP BY clause?"

Identify the weakest component in the decision argument chain:
{json.dumps(toulmin_components, indent=2)}

4.1 Analyze the Toulmin argument structure for this decision:
   - Claim: What is being asserted that can be tested with SQL?
   - Evidence: What SQL queries would provide direct supporting data?
   - Warrant: What logical relationship between columns connects evidence to the claim?
   - Backing: What historical data in the database supports the warrant?
   - Qualifier: What SQL-derivable limits affect the scope or certainty?
   - Rebuttal: What data conditions would invalidate the claim?

4.2 Identify the 1-2 weakest components in this structure:
   - Formulate a question that directly strengthens this component
   - Explain exactly how the SQL query results would reinforce the argument
   - Ensure the question is answerable with available database columns

4.3 Example SQL-answerable argument-strengthening questions:
   - For weak evidence: "What is the statistical significance (p-value) of the difference between [group A] and [group B] when calculated using SQL?"
   - For weak warrant: "When we segment the data using SQL GROUP BY, do we see the same relationship between [column X] and [column Y] across all subgroups?"
   - For weak backing: "What historical patterns in our time-series data support our assumption about [relationship Z]?"

Identify the strongest potential challenge to the decision:
{json.dumps(counterargument_categories, indent=2)}

5.1 Consider these categories of potential counter-arguments:
   - Conclusion rebuttals: Alternative outcomes from the same data
   - Premise rebuttals: Challenges to the data quality or relevance
   - Argument undercutters: Flaws in the relationship between columns
   - Framing challenges: Alternative SQL aggregations or groupings

5.2 Select the most formidable counter-argument:
   - Determine what SQL query would be needed to test this counter-argument
   - Formulate a precise question that directly addresses this challenge
   - Ensure the question references specific tables and columns

5.3 Example SQL-answerable counter-argument testing questions:
   - "If we segment the data using GROUP BY [alternative column], does the relationship between [column X] and [column Y] still hold?"
   - "What happens to our calculated metrics if we exclude outliers above the 95th percentile using a WHERE clause?"
   - "Is there a non-linear relationship between [column X] and [column Y] that we could detect by binning the data in SQL?"

6.1 Identify time-based patterns critical to the decision:
   - Identify date/timestamp columns in the schema
   - Formulate SQL questions that explore how key metrics have changed over time
   - Consider seasonality, growth rates, or pattern shifts that can be detected with SQL

6.2 Example SQL-answerable trend validation questions:
   - "How has the correlation between [column X] and [column Y] changed over time when grouped by quarter using SQL date functions?"
   - "At what point in our time series did [metric] begin to show significant change, as determined by a moving average calculation in SQL?"
   - "Are the patterns we observe consistent across different time aggregations (daily, monthly, yearly) when using SQL date functions?"

**Critical:** Produce a minimal set of questions by:

7.1 Evaluate each candidate question on these dimensions:
   - **Decision impact**: How significantly would the answer change the decision? (High/Medium/Low)
   - **Answerability**: How directly can it be answered with available data? (High/Medium/Low)
   - **Uniqueness**: Does it provide insight not covered by other questions? (High/Medium/Low)
   - **Bias mitigation**: Does it address a critical cognitive vulnerability? (High/Medium/Low)
   - **Causal Identification Strength**: Does the question explicitly state the assumptions required for the chosen identification strategy to be valid?

7.2 Prioritize questions with the highest combined score across these dimensions
   - Retain only the top 4 questions that collectively provide the most decision value
   - Ensure at least one question from each critical pillar is included
   - Apply a self-critique to each final question: "How might this question fail to produce useful insight?"
   - Revise questions that fail this critique

7.3 Final check:
   - Verify each question is directly answerable with SQL queries
   - Ensure each question has a clear, unique purpose
   - Confirm the set collectively builds toward a hard-to-vary explanation
   - Ensure that the data elements referenced in the questions are actually present in the schema.
   - Ensure that each refinement question utilizes a distinct data element or addresses a unique aspect of the decision context not covered by other questions.



**Decision:** Should we offer a special service to clients who choose weekly statement issuance?

**Good SQL-Answerable Question:** "What is the average revenue (from the account_revenue table) generated by clients who opt for weekly statements compared to those who choose monthly statements, and does this difference exceed 10%? This question directly tests whether the statement frequency preference correlates with revenue potential."

**Poor Question:** "Do clients prefer weekly statements?" (Too vague, doesn't reference specific database columns, and isn't structured for SQL analysis).

For optimal streaming output, first provide your analysis, then deliver questions. Format your response as a JSON array, with one object for each dataset entry:

```json
[
  {{
    "dataset_id": 1,
    "bird_id": 101,
    "analysis": {{
      "decision_context_summary": "Brief analysis of the key decision points",
      "critical_data_elements": ["table1.column1", "table2.column2"],
      "potential_biases": ["confirmation bias", "availability bias"],
      "data_quality_concerns": ["high nulls in table3.column4", "skewed distribution in table1.column5"],
      "argument_structure": {{
        "claim": "The main assertion testable with SQL",
        "evidence_sources": ["Specific tables and columns that would provide evidence"],
        "potential_counterarguments": ["Alternative explanations that could be tested with SQL"]
      }}
    }},
    "primary_question": {{
      "question": "SQL-answerable question that directly addresses the core decision need",
      "sql_tables_columns": ["Specific tables and columns referenced"],
      "explanation": "How this question addresses the core decision need"
    }},
    "refinement_questions": [
      {{
        "question": "SQL-answerable question with specific column references",
        "sql_tables_columns": ["table1.column1", "table2.column2"],
        "pillar": "One of: 'Vulnerability Assessment', 'Data Structure Validation', 'Argument Strengthening', 'Counter-Argument Testing', or 'Temporal Analysis'",
        "component": "The specific component within the pillar",
        "decision_impact": "How SQL results would improve the decision",
        "bias_addressed": "If applicable, the specific cognitive bias this helps mitigate",
        "data_quality_dimension": "If applicable, the data quality issue addressed",
        "argument_component": "If applicable, the specific Toulmin component strengthened",
        "counter_argument_type": "If applicable, the type of counter-argument tested",
        "rationale": "Why this question is in the top 3-4 most valuable questions"
      }}
      // Only up to 5 refinement questions maximum
    ]
  }}
]
```

1. **Generate specific, not general questions** - "How does the average loan default rate vary by income quintile?" not "How do demographics affect defaults?"
2. **Prioritize decision relevance**
3. **Maximum of 4 refinement questions** per dataset entry
4. **Every question must be directly answerable** using SQL queries against the database schema
5. **Questions must explicitly connect** to data columns and tables in the schema
6. **Ensure questions address trends and alternative explanations** which are often overlooked
7. **Self-critique each question** to ensure it provides unique, actionable insight
8. **Questions should build toward hard-to-vary explanations** by being specific, data-constrained, and falsifiable
9. **Consider cost-benefit, motivations, unintended consequences, and selection bias**
10. **Address potential reverse causality**
11. **Explore heterogeneous treatment effects**
12. **Address data quality issues**
13. **Consider long-term effects**
14. **Enhance generalizability**
15. **Mitigate over-reliance on statistical techniques**
16. **Consider strategic motivations**
17. **Build a logical argument**
18. **Consider qualitative aspects and systemic issues**
19. **Perform temporal analysis**
20. **Consider organizational culture**
21. **Challenge user assumptions**
22. **Address confirmation bias**
23. **Expand scope to other relevant factors**
24. **Explore causal relationships**
25. **Explicitly state acceptable risk level**
26. **Consider confounding factors**
27. **Address ethical considerations**
28. **Explore alternative solutions**
29. **Focus on actor well-being**
30. **Elicit counterarguments**
31. **Consider base rates**
32. **Explore alternative explanations and strategies**
33. **Perform forward-looking analysis and falsifiable predictions**
34. **Provide backing and qualifiers for claims**
35. **Consider qualitative data**
36. **Address illusion of control, groupthink, and opportunity cost biases**
37. **Reduce redundancy in questions**
38. **Incorporate qualitative insights**
39. **Ensure questions are answerable using only the provided schema**
40. **Ensure that the data elements referenced in the questions are actually present in the schema**
41. **Ensure that each refinement question utilizes a distinct data element or addresses a unique aspect of the decision context not covered by other questions.
"""
    return prompt


def get_flash_response_schema():
    response_schema = {'type': 'ARRAY', 'items': {'type': 'OBJECT',
        'properties': {'dataset_id': {'type': 'INTEGER'}, 'bird_id': {
        'type': 'INTEGER'}, 'analysis': {'type': 'OBJECT', 'properties': {
        'decision_context_summary': {'type': 'STRING'},
        'critical_data_elements': {'type': 'ARRAY', 'items': {'type':
        'STRING'}}, 'potential_biases': {'type': 'ARRAY', 'items': {'type':
        'STRING'}}, 'data_quality_concerns': {'type': 'ARRAY', 'items': {
        'type': 'STRING'}}, 'argument_structure': {'type': 'OBJECT',
        'properties': {'claim': {'type': 'STRING'}, 'evidence_sources': {
        'type': 'ARRAY', 'items': {'type': 'STRING'}},
        'potential_counterarguments': {'type': 'ARRAY', 'items': {'type':
        'STRING'}}}}}}, 'primary_question': {'type': 'OBJECT', 'properties':
        {'question': {'type': 'STRING'}, 'sql_tables_columns': {'type':
        'ARRAY', 'items': {'type': 'STRING'}}, 'explanation': {'type':
        'STRING'}}, 'required': ['question', 'sql_tables_columns',
        'explanation']}, 'refinement_questions': {'type': 'ARRAY', 'items':
        {'type': 'OBJECT', 'properties': {'question': {'type': 'STRING'},
        'sql_tables_columns': {'type': 'ARRAY', 'items': {'type': 'STRING'}
        }, 'pillar': {'type': 'STRING'}, 'component': {'type': 'STRING'},
        'decision_impact': {'type': 'STRING'}, 'bias_addressed': {'type':
        'STRING'}, 'data_quality_dimension': {'type': 'STRING'},
        'argument_component': {'type': 'STRING'}, 'counter_argument_type':
        {'type': 'STRING'}, 'rationale': {'type': 'STRING'}}, 'required': [
        'question', 'sql_tables_columns', 'pillar', 'component',
        'decision_impact', 'rationale']}}}, 'required': ['dataset_id',
        'bird_id', 'primary_question', 'refinement_questions']}}
    return response_schema


def query_claude(prompt):
    try:
        logging.info('Sending batch request to Claude API using streaming')
        logging.info(f'PROMPT (truncated):\n{prompt[:50000]}...')
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
        response_file = f'logs/claude_response_{timestamp}.txt'
        with open(response_file, 'w', encoding='utf-8') as f:
            f.write(response_text)
        logging.info(f'Full response saved to {response_file}')
        logging.info(f'THINKING (truncated):\n{thinking_text[:1000000]}...')
        logging.info(f'RESPONSE (truncated):\n{response_text[:1000000]}...')
        try:
            json_start = response_text.find('```json')
            if json_start != -1:
                json_start += 7
                json_end = response_text.find('```', json_start)
                if json_end != -1:
                    json_str = response_text[json_start:json_end].strip()
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError as e:
                        logging.error(
                            f'Error parsing JSON in code block: {str(e)}')
            json_start = response_text.find('```')
            if json_start != -1:
                json_start += 3
                json_end = response_text.find('```', json_start)
                if json_end != -1:
                    json_str = response_text[json_start:json_end].strip()
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError as e:
                        logging.error(
                            f'Error parsing JSON in unmarked code block: {str(e)}'
                            )
            array_start = response_text.find('[')
            if array_start != -1:
                array_end = -1
                open_brackets = 0
                for i in range(array_start, len(response_text)):
                    if response_text[i] == '[':
                        open_brackets += 1
                    elif response_text[i] == ']':
                        open_brackets -= 1
                        if open_brackets == 0:
                            array_end = i + 1
                            break
                if array_end != -1:
                    json_str = response_text[array_start:array_end].strip()
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError as e:
                        logging.error(
                            f'Error parsing direct JSON array: {str(e)}')
            try:
                return json.loads(response_text)
            except json.JSONDecodeError:
                logging.error('Failed to parse full response as JSON')
            logging.error('All JSON parsing attempts failed')
            return []
        except Exception as e:
            logging.error(f'Unexpected error during JSON parsing: {str(e)}')
            logging.error(traceback.format_exc())
            return []
    except Exception as e:
        logging.error(f'Error calling Claude API: {str(e)}')
        logging.error(traceback.format_exc())
        return []


def query_flash(content_prompt):
    try:
        logging.info(
            'Sending batch request to Flash (Gemini) API using streaming')
        logging.info(f'CONTENT PROMPT (truncated): {content_prompt[:500]}...')
        response_schema = get_flash_response_schema()
        logging.info(f'Using response schema: {json.dumps(response_schema)}')
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
        logging.info(f'RESPONSE length: {len(response_text)} bytes')
        logging.info(
            f'RESPONSE from Flash (first 50000 chars): {response_text[:50000]}...'
            )
        try:
            parsed_response = json.loads(response_text)
            logging.info('Successfully parsed JSON directly')
            return parsed_response
        except json.JSONDecodeError as e:
            logging.warning(f'Direct JSON parsing failed: {str(e)}')
            if not response_text.strip().endswith(']'):
                logging.warning(
                    'Response appears to be truncated - attempting recovery')
                last_object_end = response_text.rfind('},')
                if last_object_end > 0:
                    fixed_json = response_text[:last_object_end + 1] + ']'
                    try:
                        parsed_response = json.loads(fixed_json)
                        logging.info(
                            f'Successfully recovered {len(parsed_response)} complete objects from truncated response'
                            )
                        return parsed_response
                    except json.JSONDecodeError as e2:
                        logging.error(f'Recovery attempt failed: {str(e2)}')
            logging.error('All JSON parsing attempts failed')
            return []
    except Exception as e:
        logging.error(f'Error calling Flash API: {str(e)}')
        logging.error(traceback.format_exc())
        return []


def insert_primary_question(conn, dataset_id, primary_question_data):
    try:
        cursor = conn.cursor()
        nl_question = primary_question_data.get('question', '')
        if not nl_question:
            logging.warning(
                f'Empty primary question text for dataset_id {dataset_id}')
            return False
        framework_details = {'explanation': primary_question_data.get(
            'explanation', ''), 'type': 'primary_question',
            'sql_tables_columns': primary_question_data.get(
            'sql_tables_columns', [])}
        cursor.execute(
            """
            INSERT INTO query 
            (dataset_id, query_model, NL_question, model_query_sequence_index, 
             framework_details, framework_contribution_factor_name, sql_generation_status, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            , (dataset_id, 'baqr', nl_question, 1, json.dumps(
            framework_details), 'Primary Question', 'pending', 'active'))
        conn.commit()
        cursor.close()
        logging.info(
            f'Successfully inserted primary question for dataset_id {dataset_id}'
            )
        return True
    except Exception as e:
        logging.error(f'Error inserting primary question: {str(e)}')
        return False


def insert_refinement_questions(conn, dataset_id, refinement_questions):
    try:
        cursor = conn.cursor()
        for idx, question_data in enumerate(refinement_questions, start=2):
            nl_question = question_data.get('question', '')
            if not nl_question:
                logging.warning(
                    f'Empty refinement question text found for dataset_id {dataset_id}, index {idx}'
                    )
                continue
            pillar = question_data.get('pillar', '')
            component = question_data.get('component', '')
            framework_factor = 'Unknown'
            if pillar == 'Vulnerability Assessment':
                framework_factor = 'Bias Mitigation'
            elif pillar == 'Data Structure Validation':
                framework_factor = 'Data Structure Validation'
            elif pillar == 'Argument Strengthening':
                framework_factor = 'Argument Enhancement'
            elif pillar == 'Counter-Argument Testing':
                framework_factor = 'Counter-Argument Testing'
            elif pillar == 'Temporal Analysis':
                framework_factor = 'Temporal Analysis'
            framework_details = {'pillar': pillar, 'component': component,
                'decision_impact': question_data.get('decision_impact', ''),
                'bias_addressed': question_data.get('bias_addressed', ''),
                'data_quality_dimension': question_data.get(
                'data_quality_dimension', ''), 'argument_component':
                question_data.get('argument_component', ''),
                'counter_argument_type': question_data.get(
                'counter_argument_type', ''), 'rationale': question_data.
                get('rationale', ''), 'sql_tables_columns': question_data.
                get('sql_tables_columns', []), 'type': 'refinement_question'}
            cursor.execute(
                """
                INSERT INTO query 
                (dataset_id, query_model, NL_question, model_query_sequence_index, 
                 framework_details, framework_contribution_factor_name, sql_generation_status, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """
                , (dataset_id, 'baqr', nl_question, idx, json.dumps(
                framework_details), framework_factor, 'pending', 'active'))
        conn.commit()
        cursor.close()
        logging.info(
            f'Successfully inserted {len(refinement_questions)} refinement questions for dataset_id {dataset_id}'
            )
        return True
    except Exception as e:
        logging.error(f'Error inserting refinement questions: {str(e)}')
        return False


def process_batch_response(conn, records, responses):
    data_lookup = {record['id']: record for record in records}
    if not responses:
        logging.error('No responses to process')
        handle_failed_batch(conn, records)
        return
    logging.info(f'Processing {len(responses)} responses')
    response_ids = [response.get('dataset_id') for response in responses if
        isinstance(response, dict) and response.get('dataset_id') is not None]
    missing_ids = [record_id for record_id in data_lookup.keys() if 
        record_id not in response_ids]
    if missing_ids:
        logging.warning(
            f'Missing responses for {len(missing_ids)} records: {missing_ids}')
        try:
            cursor = conn.cursor()
            placeholders = ', '.join(['%s'] * len(missing_ids))
            cursor.execute(
                f"UPDATE dataset SET baqr_status = 'failed' WHERE id IN ({placeholders})"
                , missing_ids)
            conn.commit()
            cursor.close()
            logging.info(
                f'Marked {len(missing_ids)} records as failed due to missing responses'
                )
        except Exception as e:
            logging.error(f'Error marking records as failed: {str(e)}')
    for response in responses:
        if not isinstance(response, dict):
            logging.error(
                f'Invalid response object (not a dict): {type(response)}')
            continue
        dataset_id = response.get('dataset_id')
        if dataset_id is None:
            logging.error(f'Missing dataset_id in response: {response}')
            continue
        if dataset_id not in data_lookup:
            logging.error(f'Dataset ID {dataset_id} not found in current batch'
                )
            continue
        primary_question = response.get('primary_question', {})
        if not isinstance(primary_question, dict
            ) or 'question' not in primary_question:
            logging.error(
                f'Invalid primary_question for dataset_id {dataset_id}: {primary_question}'
                )
            continue
        refinement_questions = response.get('refinement_questions', [])
        if not isinstance(refinement_questions, list):
            logging.error(
                f'Invalid refinement_questions for dataset_id {dataset_id}: {refinement_questions}'
                )
            continue
        try:
            if not insert_primary_question(conn, dataset_id, primary_question):
                logging.error(
                    f'Failed to insert primary question for dataset_id {dataset_id}'
                    )
                continue
            valid_refinement_questions = []
            for q in refinement_questions:
                if not isinstance(q, dict):
                    logging.warning(
                        f'Skipping non-dict refinement question: {q}')
                    continue
                required_fields = ['question', 'pillar', 'component',
                    'decision_impact', 'rationale']
                if all(field in q for field in required_fields):
                    if 'sql_tables_columns' not in q:
                        q['sql_tables_columns'] = []
                    valid_refinement_questions.append(q)
                else:
                    missing = [f for f in required_fields if f not in q]
                    logging.warning(
                        f'Skipping refinement question with missing fields {missing}: {q}'
                        )
            if valid_refinement_questions:
                valid_refinement_questions = valid_refinement_questions[:5]
                insert_refinement_questions(conn, dataset_id,
                    valid_refinement_questions)
                logging.info(
                    f'Inserted {len(valid_refinement_questions)} refinement questions for dataset_id {dataset_id}'
                    )
            else:
                logging.warning(
                    f'No valid refinement questions for dataset_id {dataset_id}'
                    )
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE dataset SET baqr_status = 'success' WHERE id = %s",
                (dataset_id,))
            conn.commit()
            cursor.close()
            logging.info(f"Updated dataset {dataset_id} status to 'success'")
        except Exception as e:
            logging.error(
                f'Error processing response for dataset_id {dataset_id}: {str(e)}'
                )
            logging.error(traceback.format_exc())
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE dataset SET baqr_status = 'failed' WHERE id = %s",
                    (dataset_id,))
                conn.commit()
                cursor.close()
            except Exception as inner_e:
                logging.error(
                    f"Failed to update dataset status to 'failed' for dataset_id {dataset_id}: {str(inner_e)}"
                    )


def handle_failed_batch(conn, records):
    try:
        cursor = conn.cursor()
        ids = [record['id'] for record in records]
        placeholders = ', '.join(['%s'] * len(ids))
        cursor.execute(
            f"UPDATE dataset SET baqr_status = 'failed' WHERE id IN ({placeholders})"
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
        f'Starting baqr_question_generator.py script with {LLM_MODEL} model')
    try:
        evidence_data, schema_data, stats_data, pillar_data = load_files()
        logging.info(
            'Successfully loaded evidence, schema, stats, and pillar files')
        conn = get_db_connection()
        logging.info('Successfully connected to the database')
        batch_count = 0
        current_batch_size = BATCH_SIZE
        while True:
            batch_count += 1
            batch_start_time = time.time()
            records = get_dataset_records(conn, current_batch_size)
            logging.info(
                f'Batch {batch_count}: Found {len(records)} records to process'
                )
            if not records:
                logging.info('No more records to process. Exiting.')
                break
            logging.info(
                f'Processing batch {batch_count} with {len(records)} records')
            prompt = prepare_prompt(records, evidence_data, schema_data,
                stats_data, pillar_data)
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
