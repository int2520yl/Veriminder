function analysisResultDisplay(data) {
    const resultsSection = document.getElementById('analysis-results');
    if (resultsSection) {
        resultsSection.style.display = 'block';
    }

    const streamingContainer = document.getElementById('analysis-streaming');
    if (streamingContainer) {
        streamingContainer.style.display = 'none';
    }

    const initialContainer = document.getElementById('initial-analysis');
    if (initialContainer && data.initialAnalysis) {
        let content = '';

        if (data.initialAnalysis.summary) {
            content += `<h6>Summary</h6><p>${data.initialAnalysis.summary}</p>`;
        }

        if (data.initialAnalysis.detailed_analysis) {
            content += `<h6>Detailed Analysis</h6><p>${data.initialAnalysis.detailed_analysis}</p>`;
        }

        initialContainer.innerHTML = content || '<p class="text-muted">No analysis available for initial query.</p>';
    }

    const comprehensiveContainer = document.getElementById('comprehensive-analysis');
    if (comprehensiveContainer && data.comprehensiveAnalysis) {
        let content = '';

        if (data.comprehensiveAnalysis.summary) {
            content += `<h6>Summary</h6><p>${data.comprehensiveAnalysis.summary}</p>`;
        }

        if (data.comprehensiveAnalysis.detailed_analysis) {
            content += `<h6>Detailed Analysis</h6><p>${data.comprehensiveAnalysis.detailed_analysis}</p>`;
        }

        comprehensiveContainer.innerHTML = content || '<p class="text-muted">No analysis available for refinement queries.</p>';
    }
}

function decisionQuestionSqlResultDisplay(data) {
    const resultsContainer = document.getElementById('initial-results');
    if (resultsContainer) {
        resultsContainer.style.display = 'block';
    }

    const reasoningLoader = document.querySelector('#reasoning-content .reasoning-loader');
    if (reasoningLoader) {
        reasoningLoader.style.display = 'none';
    }

    const streamingContainer = document.getElementById('nl-to-sql-streaming');
    if (streamingContainer) {
        streamingContainer.style.display = 'none';
    }

    const reasoningText = document.querySelector('#reasoning-content .reasoning-text');
    if (reasoningText) {
        reasoningText.style.display = 'block';
        reasoningText.innerHTML = data.reasoning || 'No reasoning information available.';
    }

    const answerContent = document.getElementById('answer-content');
    if (answerContent) {
        answerContent.innerHTML = data.answer || 'No answer available.';
    }

    const sqlQuery = document.getElementById('sql-query');
    if (sqlQuery) {
        sqlQuery.textContent = data.sql || '-- No SQL query available';
    }

    showAndScrollTo('initial-results');
}

function explanation(suggestion) {
    if (suggestion.rationale && suggestion.rationale.trim()) {
        return suggestion.rationale;
    }

    if (suggestion.purpose && suggestion.purpose.trim()) {
        return suggestion.purpose;
    }

    if (suggestion.pillar && suggestion.component) {
        return `${suggestion.pillar}: ${suggestion.component}`;
    }

    return "Provides additional insight for your analysis";
}

function feedbackAckDisplay(prolificCode) {
    const form = document.getElementById('feedback-form');
    if (form) {
        form.style.display = 'none';
    }

    const successMessage = document.getElementById('feedback-success');
    if (successMessage) {
        successMessage.innerHTML = `
            <h4 class="alert-heading"><i class="fas fa-check-circle me-2"></i>Thank you for your feedback!</h4>
            <p>Your feedback has been successfully submitted and will help us improve our tool.</p>
        `;
        successMessage.style.display = 'block';
    }
}

function selectedSuggestionsSqlResultDisplay(data) {
    const loadingIndicator = document.getElementById('suggestion-reasoning-loader');
    if (loadingIndicator) {
        loadingIndicator.style.display = 'none';
    }

    const streamingContainer = document.getElementById('process-suggestions-streaming');
    if (streamingContainer) {
        streamingContainer.style.display = 'none';
    }

    const reasoningContent = document.getElementById('suggestion-reasoning-content');
    if (reasoningContent && data.reasoning) {
        reasoningContent.innerHTML = `<p>${data.reasoning}</p>`;
        reasoningContent.style.display = 'block';
    }

    const answersContainer = document.getElementById('suggestion-answers');
    if (!answersContainer) return;

    const answers = data.answers || [];
    const queries = data.queries || [];

    if (!answers.length) {
        answersContainer.innerHTML = '<div class="alert alert-info">No results available.</div>';
        return;
    }

    answersContainer.innerHTML = '';

    answers.forEach((answer, index) => {
        const query = queries.find(q => q.query_id === answer.query_id) || { sql: 'No SQL query available' };

        const resultDiv = document.createElement('div');
        resultDiv.className = 'suggestion-result mb-4 p-3 bg-light rounded';

        const headerDiv = document.createElement('div');
        headerDiv.className = 'd-flex align-items-center mb-2';

        const questionHeader = document.createElement('h5');
        questionHeader.className = 'mb-0 me-2';
        questionHeader.textContent = `Q${index + 1}: ${answer.question || 'Unknown Question'}`;

        const tooltip = createQueryTooltip(query.sql);

        headerDiv.appendChild(questionHeader);
        headerDiv.appendChild(tooltip);

        const answerContent = document.createElement('div');
        answerContent.className = 'answer-content';

        if (answer.error) {
            answerContent.innerHTML = `<div class="alert alert-danger">${answer.error}</div>`;
        } else {
            answerContent.innerHTML = answer.answer || 'No answer available';
        }

        resultDiv.appendChild(headerDiv);
        resultDiv.appendChild(answerContent);

        answersContainer.appendChild(resultDiv);
    });
}

function suggestionOptionsDisplay(suggestions) {
    const suggestionsListElement = document.getElementById('suggestions-list');
    const suggestionsLoading = document.getElementById('suggestions-loading');
    const submitButton = document.getElementById('submit-suggestions');

    const streamingContainer = document.getElementById('suggestions-streaming');
    if (streamingContainer) {
        streamingContainer.style.display = 'none';
    }

    if (!suggestionsListElement) return;

    if (suggestionsLoading) {
        suggestionsLoading.style.display = 'none';
    }

    suggestionsListElement.innerHTML = '';

    if (!suggestions || suggestions.length === 0) {
        suggestionsListElement.innerHTML = '<div class="alert alert-info">No suggestions available for this question. Try a different question that relates to the available dataset.</div>';
        return;
    }

    suggestions.forEach((suggestion, index) => {
        const listItem = document.createElement('div');
        listItem.className = 'suggestion-item form-check mb-3 p-2 border-bottom';

        const isStudyMode = window.isStudyMode;
        const checked = isStudyMode ? 'checked' : '';
        const disabled = isStudyMode ? 'disabled' : '';

        if (suggestion.pillar) listItem.dataset.pillar = suggestion.pillar;
        if (suggestion.component) listItem.dataset.component = suggestion.component;
        if (suggestion.purpose) listItem.dataset.purpose = suggestion.purpose;
        if (suggestion.rationale) listItem.dataset.rationale = suggestion.rationale;

        if (suggestion.query_id) {
            listItem.dataset.queryId = suggestion.query_id;
        }

        let explanationText = '';
        if (suggestion.rationale) {
            explanationText = suggestion.rationale;
        } else if (suggestion.purpose) {
            explanationText = suggestion.purpose;
        }

        listItem.innerHTML = `
            <div class="d-flex align-items-start">
                <input class="form-check-input mt-1 me-2" type="checkbox" value="${index}" 
                    id="suggestion-${index}" ${checked} ${disabled}>
                <div>
                    <label class="form-check-label fw-bold" for="suggestion-${index}">
                        ${suggestion.question || 'No question available'}
                    </label>
                    <div class="suggestion-explanation text-muted small mt-1">
                        <span class="text-secondary">${explanation(suggestion)}</span>
                    </div>
                </div>
            </div>
        `;

        suggestionsListElement.appendChild(listItem);
    });

    if (submitButton) {
        submitButton.style.display = 'block';
    }
}
