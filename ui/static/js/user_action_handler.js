function analysisRequestSubmit() {
    if (submissionState.analysisRequest) {
        return;
    }

    if (!window.datasetId) {
        alert('Missing dataset information. Please reload the page.');
        return;
    }

    submissionState.analysisRequest = true;

    document.getElementById('analysis-request').style.display = 'none';

    const streamingContainer = document.getElementById('analysis-streaming');
    if (streamingContainer && window.userId) {
        streamingContainer.style.display = 'block';

        window.initializeStreaming('analysis', window.datasetId, function (data) {
            window.updateStreamUI(
                'analysis-streaming',
                'analysis-status',
                'analysis-progress-bar',
                'analysis-message',
                data
            );

            if (data.status === 'complete' || data.status === 'error') {
                setTimeout(() => {
                    streamingContainer.style.display = 'none';
                }, 1000);
            }
        });
    } else {
        document.getElementById('analysis-loading').style.display = 'block';
    }

    fetch(`/api/analysis/${window.datasetId}`, {
        method: 'GET',
        headers: {'Content-Type': 'application/json'}
    })
        .then(async response => {
            if (!response.ok) {
                const friendlyMessage = await getFriendlyErrorMessage(response);
                throw new Error(friendlyMessage);
            }
            return response.json();
        })
        .then(data => {
            document.getElementById('analysis-loading').style.display = 'none';
            if (streamingContainer) {
                streamingContainer.style.display = 'none';
            }

            analysisResultDisplay(data);

            document.getElementById('feedback-container').style.display = 'block';
        })
        .catch(error => {
            console.error('Error fetching analysis:', error);

            document.getElementById('analysis-loading').style.display = 'none';
            if (streamingContainer) {
                streamingContainer.style.display = 'none';
            }

            document.getElementById('analysis-results').innerHTML = `
            <div class="alert alert-danger">
                <h5><i class="fas fa-exclamation-triangle me-2"></i>Error Retrieving Analysis</h5>
                <p>${error.message || 'Due to limitations of the available dataset, we are not able to generate an analysis. Please try with a different question.'}</p>
                <button class="btn btn-outline-danger mt-2" onclick="location.reload()">
                    <i class="fas fa-sync me-2"></i>Try Again
                </button>
            </div>
        `;
            document.getElementById('analysis-results').style.display = 'block';
        })
        .finally(() => {
            submissionState.analysisRequest = false;

            closeStream('analysis');
        });
}

function countWords(text) {
    return text.trim().split(/\s+/).filter(word => word.length > 0).length;
}

function decisionQuestionSubmit(event) {
    event.preventDefault();

    if (submissionState.questionForm) {
        return false;
    }

    const questionField = document.getElementById('question');
    const decisionField = document.getElementById('decision');

    submissionState.questionForm = true;

    showButtonLoading('submit-question', 'Processing...');

    questionField.readOnly = true;
    decisionField.readOnly = true;

    const tempStreamingId = window.datasetId || generateStreamingId(window.userId);

    const formData = {
        dataset_id: window.datasetId || '',
        user_id: window.userId || '',
        question: questionField.value.trim(),
        decision: decisionField.value.trim(),
        streaming_id: tempStreamingId
    };

    const nlToSqlStreamingContainer = document.getElementById('nl-to-sql-streaming');
    if (nlToSqlStreamingContainer && formData.user_id) {
        nlToSqlStreamingContainer.style.display = 'block';

        window.initializeStreaming('nl_to_sql', tempStreamingId, function (data) {
            console.log("Received stream update for nl_to_sql:", data);

            window.updateStreamUI(
                'nl-to-sql-streaming',
                'nl-to-sql-status',
                'nl-to-sql-progress-bar',
                'nl-to-sql-message',
                data
            );

            if (data.status === 'complete' || data.status === 'error') {
                setTimeout(() => {
                    nlToSqlStreamingContainer.style.display = 'none';
                }, 1000);
            }
        });
    }

    const suggestionsStreamingContainer = document.getElementById('suggestions-streaming');
    if (suggestionsStreamingContainer && formData.user_id) {
        suggestionsStreamingContainer.style.display = 'block';

        window.initializeStreaming('suggestions', tempStreamingId, function (data) {
            console.log("Received stream update for suggestions:", data);

            window.updateStreamUI(
                'suggestions-streaming',
                'suggestions-status',
                'suggestions-progress-bar',
                'suggestions-message',
                data
            );

            if (data.status === 'complete' || data.status === 'error') {
                setTimeout(() => {
                    suggestionsStreamingContainer.style.display = 'none';
                }, 1000);
            }
        });
    }

    document.getElementById('suggestions-container').style.display = 'block';

    Promise.all([
        fetch('/api/nl-to-sql', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(formData)
        })
            .then(async response => {
                if (!response.ok) {
                    const friendlyMessage = await getFriendlyErrorMessage(response);
                    throw new Error(friendlyMessage);
                }
                return response.json();
            }),

        fetch('/api/suggestions', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(formData)
        })
            .then(async response => {
                if (!response.ok) {
                    const friendlyMessage = await getFriendlyErrorMessage(response);
                    throw new Error(friendlyMessage);
                }
                return response.json();
            })
    ])
        .then(([nlToSqlResponse, suggestionsResponse]) => {
            if (nlToSqlResponse.dataset_id && !window.datasetId) {
                window.datasetId = nlToSqlResponse.dataset_id;

            }

            decisionQuestionSqlResultDisplay(nlToSqlResponse);

            suggestionOptionsDisplay(suggestionsResponse.suggestions || []);

            if (!window.isStudyMode) {
                questionField.readOnly = false;
                decisionField.readOnly = false;
            }
        })
        .catch(error => {
            console.error('Error processing form:', error);

        })
        .finally(() => {
            submissionState.questionForm = false;

            resetButton('submit-question');

            closeStream('nl_to_sql');
            closeStream('suggestions');
        });

    return false;
}

function feedbackSubmit(event) {
    event.preventDefault();

    if (submissionState.feedbackForm) {
        return false;
    }

    const form = document.getElementById('feedback-form');
    const submitButton = document.getElementById('submit-feedback-btn');
    const errorContainer = document.getElementById('feedback-error');

    const scenarioRealism = parseInt(document.querySelector('input[name="scenario_realism"]:checked')?.value || '0', 10);
    const suggestionEffectiveness = parseInt(document.querySelector('input[name="suggestion_effectiveness"]:checked')?.value || '0', 10);
    const rationaleClarity = parseInt(document.querySelector('input[name="rationale_clarity"]:checked')?.value || '0', 10);
    const questionImpact = parseInt(document.querySelector('input[name="question_impact"]:checked')?.value || '0', 10);

    if (!scenarioRealism || !suggestionEffectiveness || !rationaleClarity || !questionImpact) {
        showError('feedback-error', 'Please rate all aspects before submitting your feedback.');
        return false;
    }

    hideError('feedback-error');

    const feedbackData = {
        dataset_id: window.datasetId,
        user_id: window.userId,
        scenario_realism: scenarioRealism,
        suggestion_effectiveness: suggestionEffectiveness,
        rationale_clarity: rationaleClarity,
        question_impact: questionImpact
    };

    submissionState.feedbackForm = true;

    showButtonLoading('submit-feedback-btn', 'Submitting...');

    fetch('/api/user_feedback/', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(feedbackData)
    })
        .then(async response => {
            if (!response.ok) {
                const friendlyMessage = await getFriendlyErrorMessage(response);
                throw new Error(friendlyMessage);
            }
            return response.json();
        })
        .then(data => {
            if (data.success) {
                feedbackAckDisplay(data.prolific_code);
            } else {
                throw new Error(data.error || 'Failed to submit feedback.');
            }
        })
        .catch(error => {
            console.error('Error submitting feedback:', error);

            showError('feedback-error', error.message || 'Failed to submit feedback. Please try again.');
        })
        .finally(() => {
            submissionState.feedbackForm = false;

            resetButton('submit-feedback-btn');
        });

    return false;
}

function generateStreamingId(userId) {
    return `${userId}_${Date.now()}`;
}

async function getFriendlyErrorMessage(response) {
    try {
        const data = await response.json();
        if (data && data.message) return data.message;
        if (data && data.error) return data.error;
    } catch (e) {
        console.log("Error parsing JSON response:", e);
    }

    return "Due to limitations of the available dataset, we are not able to satisfy your request. Please try with a different question.";
}

function getSelectedSuggestions() {
    const selectedSuggestions = [];
    const checkboxes = document.querySelectorAll('#suggestions-list input[type="checkbox"]:checked');

    checkboxes.forEach(checkbox => {
        const container = checkbox.closest('.suggestion-item');
        if (container) {
            const suggestionData = {
                question: "",
                pillar: container.dataset.pillar || "",
                component: container.dataset.component || "",
                purpose: container.dataset.purpose || "",
                rationale: container.dataset.rationale || ""
            };

            if (container.dataset.queryId) {
                suggestionData.query_id = container.dataset.queryId;
            }

            const questionLabel = container.querySelector('label');
            if (questionLabel) {
                suggestionData.question = questionLabel.textContent.trim();
            }

            if (!suggestionData.purpose) {
                const purposeDiv = container.querySelector('.suggestion-purpose');
                if (purposeDiv) {
                    suggestionData.purpose = purposeDiv.textContent.trim();
                }
            }

            selectedSuggestions.push(suggestionData);
        }
    });

    return selectedSuggestions;
}

function suggestionSelectionSubmit() {
    if (submissionState.suggestionForm) {
        return;
    }

    const selectedSuggestions = getSelectedSuggestions();

    if (selectedSuggestions.length === 0) {
        showError('suggestions-error', 'Please select at least one suggestion.');
        return;
    }

    hideError('suggestions-error');

    submissionState.suggestionForm = true;

    showButtonLoading('submit-suggestions', 'Processing...');

    const resultsContainer = document.getElementById('suggestion-results');
    if (resultsContainer) {
        resultsContainer.style.display = 'block';
    }

    const loadingIndicator = document.getElementById('suggestion-reasoning-loader');
    if (loadingIndicator) {
        loadingIndicator.style.display = 'block';
    }

    if (window.datasetId && window.userId) {
        const streamingContainer = document.getElementById('process-suggestions-streaming');
        if (streamingContainer) {
            streamingContainer.style.display = 'block';

            console.log("Initializing stream for process_selected_suggestions");
            window.initializeStreaming('process_selected_suggestions', window.datasetId, function (data) {
                console.log("Received stream update for process_selected_suggestions:", data);

                window.updateStreamUI(
                    'process-suggestions-streaming',
                    'process-suggestions-status',
                    'process-suggestions-progress-bar',
                    'process-suggestions-message',
                    data
                );

                if (data.status === 'complete' || data.status === 'error') {
                    console.log("Stream complete or error, hiding container");
                    setTimeout(() => {
                        streamingContainer.style.display = 'none';
                    }, 1000);
                }
            });
        }
    }

    showAndScrollTo('suggestion-results');

    fetch('/api/suggestions/process-selected', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            dataset_id: window.datasetId,
            user_id: window.userId,
            selected_suggestions: selectedSuggestions
        })
    })
        .then(async response => {
            if (!response.ok) {
                const friendlyMessage = await getFriendlyErrorMessage(response);
                throw new Error(friendlyMessage);
            }
            return response.json();
        })
        .then(data => {
            selectedSuggestionsSqlResultDisplay(data);

            document.getElementById('analysis-container').style.display = 'block';
        })
        .catch(error => {
            console.error('Error processing suggestions:', error);

            const answersContainer = document.getElementById('suggestion-answers');
            if (answersContainer) {
                answersContainer.innerHTML = `
                <div class="alert alert-danger">
                    <h5><i class="fas fa-exclamation-triangle me-2"></i>Error Processing Suggestions</h5>
                    <p>${error.message || 'Due to limitations of the available dataset, we are not able to process these suggestions. Please try different suggestions or a different question.'}</p>
                </div>
            `;
            }

            if (loadingIndicator) {
                loadingIndicator.style.display = 'none';
            }
        })
        .finally(() => {
            submissionState.suggestionForm = false;

            resetButton('submit-suggestions');

            closeStream('process_selected_suggestions');
        });
}

const submissionState = {
    questionForm: false,
    suggestionForm: false,
    analysisRequest: false,
    feedbackForm: false
};
