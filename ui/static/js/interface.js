function createQueryTooltip(sqlQuery, position = '') {
    const tooltip = document.createElement('div');
    tooltip.className = `query-tooltip ${position}`;
    tooltip.title = 'View SQL Query';

    const icon = document.createElement('i');
    icon.className = 'fas fa-code tooltip-icon';

    const tooltipContent = document.createElement('div');
    tooltipContent.className = 'tooltip-content';

    const queryLabel = document.createElement('strong');
    queryLabel.textContent = 'SQL Query:';

    const queryCode = document.createElement('pre');
    queryCode.textContent = sqlQuery || 'No SQL query available';

    tooltipContent.appendChild(queryLabel);
    tooltipContent.appendChild(document.createElement('br'));
    tooltipContent.appendChild(queryCode);
    tooltip.appendChild(icon);
    tooltip.appendChild(tooltipContent);

    return tooltip;
}

function hideError(containerId) {
    const errorContainer = document.getElementById(containerId);
    if (errorContainer) {
        errorContainer.style.display = 'none';
    }
}

function resetButton(buttonId) {
    const button = document.getElementById(buttonId);
    if (button) {
        button.disabled = false;

        const spinner = button.querySelector('.spinner-border');
        if (spinner) {
            spinner.style.display = 'none';
        }

        const originalText = button.getAttribute('data-original-text');
        if (originalText) {
            const textSpan = button.querySelector('.btn-text');
            if (textSpan) {
                textSpan.textContent = originalText;
            } else {
                button.textContent = originalText;
            }
        }
    }
}

function showAndScrollTo(elementId, smooth = true) {
    const element = document.getElementById(elementId);
    if (element) {
        element.style.display = 'block';
        element.scrollIntoView({
            behavior: smooth ? 'smooth' : 'auto',
            block: 'start'
        });
    }
}

function showButtonLoading(buttonId, loadingText = 'Processing...') {
    const button = document.getElementById(buttonId);
    if (button) {
        button.disabled = true;

        if (!button.hasAttribute('data-original-text')) {
            button.setAttribute('data-original-text', button.textContent);
        }

        const spinner = button.querySelector('.spinner-border');
        if (spinner) {
            spinner.style.display = 'inline-block';
        }

        const textSpan = button.querySelector('.btn-text');
        if (textSpan) {
            textSpan.textContent = loadingText;
        } else {
            button.textContent = loadingText;
        }
    }
}

function showError(containerId, message) {
    const errorContainer = document.getElementById(containerId);
    if (errorContainer) {
        errorContainer.textContent = message;
        errorContainer.style.display = 'block';
    }
}
