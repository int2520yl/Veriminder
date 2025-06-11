const activeStreams = {};
const activeTextStreams = {};
window.initializeStreaming = function (operation, datasetId, updateCallback) {
    closeStream(operation);
    console.log(`Initializing stream for ${operation} with dataset ${datasetId}`);
    const source = new EventSource(`/api/stream/${operation}/${datasetId}`);
    activeStreams[operation] = source;
    source.onmessage = function (event) {
        const data = JSON.parse(event.data);
        console.log(`Stream message received for ${operation}:`, data);
        if (typeof updateCallback === 'function') {
            updateCallback(data);
        }

        if (data.status === 'complete' || data.status === 'error') {
            closeStream(operation);
        }
    };
    source.onopen = function () {
        console.log(`Stream connected for ${operation}`);
    };
    source.onerror = function (error) {
        console.error(`Stream error for ${operation}:`, error);
        closeStream(operation);
    };
    source.addEventListener('connected', function (event) {
        console.log(`Stream established for ${operation}`);
    });
    source.addEventListener('close', function (event) {
        console.log(`Stream closing for ${operation}`);
        closeStream(operation);
    });
    return source;
};
window.closeStream = function (operation) {
    if (activeStreams[operation]) {
        activeStreams[operation].close();
        delete activeStreams[operation];
        console.log(`Stream closed for ${operation}`);
    }
};
window.streamText = function (elementId, text, speed = 5) {
    const element = document.getElementById(elementId);
    if (!element) return null;
    if (activeTextStreams[elementId]) {
        activeTextStreams[elementId].cancel();
    }

    let index = 0;
    element.innerHTML = '';
    const cursor = document.createElement('span');
    cursor.className = 'typing-cursor';
    element.appendChild(cursor);
    const interval = setInterval(() => {
        if (index < text.length) {
            const char = text.charAt(index);
            const textNode = document.createTextNode(char);
            if (cursor.parentNode === element) {
                element.insertBefore(textNode, cursor);
            } else {
                element.appendChild(textNode);
                element.appendChild(cursor);
            }
            index++;
        } else {
            clearInterval(interval);
            cursor.remove();
            delete activeTextStreams[elementId];
        }
    }, Math.max(1, Math.floor(100 / speed)));
    const control = {
        cancel: () => {
            clearInterval(interval);
            if (cursor.parentNode) {
                cursor.remove();
            }
            element.innerHTML = text;
            delete activeTextStreams[elementId];
        }
    };
    activeTextStreams[elementId] = control;
    return control;
};
window.updateStreamProgress = function (progressBarId, percent) {
    const progressBar = document.getElementById(progressBarId);
    if (progressBar) {
        progressBar.style.width = `${Math.min(100, Math.max(0, percent))}%`;
    }
};
window.cancelStreamingOperation = function (operation, datasetId) {
    return fetch(`/api/stream/cancel/${operation}/${datasetId}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'}
    })
        .then(response => response.json())
        .then(data => {
            closeStream(operation);
            return data;
        });
};
window.updateStreamUI = function(containerId, statusId, progressId, messageId, data) {
    console.log("Updating UI for container:", containerId, "with data:", data);
    const statusElement = document.getElementById(statusId);
    if (statusElement) {
        statusElement.textContent = data.message || '';
    }

    if (progressId) {
        updateStreamProgress(progressId, data.progress || 0);
    }

    if (messageId && data.message) {
        const messageElement = document.getElementById(messageId);
        if (messageElement) {
            messageElement.style.display = 'block';
            messageElement.textContent = data.message;
            if (activeTextStreams[messageId]) {
                activeTextStreams[messageId].cancel();
            }
            activeTextStreams[messageId] = streamText(messageId, data.message, 10);
        }
    }

    const container = document.getElementById(containerId);
    if (container) {
        container.style.display = 'block';
        container.classList.remove('status-connecting', 'status-active', 'status-complete', 'status-error');
        if (data.status === 'starting') {
            container.classList.add('status-connecting');
        } else if (data.status === 'progress') {
            container.classList.add('status-active');
        } else if (data.status === 'complete') {
            container.classList.add('status-complete');
        } else if (data.status === 'error') {
            container.classList.add('status-error');
        }
    }
};
