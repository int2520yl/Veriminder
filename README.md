# Veriminder Quick Start Guide

This guide provides the essential steps to get the Veriminder application running locally.

### **Prerequisites**
* Python 3.8+ & `venv`
* MySQL Server
* Git

---

### **Setup Instructions**

1.  **Clone & Install Dependencies**
    ```bash
    # Clone the repository
    git clone <your-repo-url>
    cd Veriminder_Submission

    # Create and activate a virtual environment
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate

    # Install required packages
    pip install -r requirements.txt
    ```

2.  **Download BIRD Database**
    * Download the BIRD development dataset from the [BIRD Benchmark Website](https://bird-bench.github.io/).
    * Update the references to the SQLITE_DB_PATH to the dataset location in your environment.

3.  **Setup MySQL Database**
    * Ensure your MySQL server is running.
    * Create a new database.
    * Run the `database_setup.sql` script to create the necessary tables and seed data.

4.  **Configure Credentials**
    * Before running, you **must** update the `DB_CONFIG` dictionary in all relevant `.py` files with your MySQL credentials.
    * You also need to add your Google and Anthropic API keys (needed only if you plan to generate new prompt templates) in the same files.
    * Files to update are located in `ui/services/`, `prompt_builder/`, and `query_models/`.

5.  **Regenerate Prompts (Optional)**
    * If you wish to create new AI prompts, run the candidate and critic modules located in the `/prompt_builder` directory.
        ```bash
        # Example
        python prompt_builder/12_candidates.py
        python prompt_builder/3_critics.py
        python prompt_builder/run_candidate_baqr_prompt.py
        python prompt_builder/run_critics_on_candidate_data.py
        python prompt_builder/moe_prompt_builder.py
        ```

6.  **Run the Flask Webserver**
    * Navigate to the `ui` directory and run the `healthcheck.py` script.
        ```bash
        cd ui
        python healthcheck.py
        ```

7.  **Access the Application**
    * Open your web browser and go to:
        **`http://localhost`**