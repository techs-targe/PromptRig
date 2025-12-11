/**
 * Prompt Evaluation System - Phase 2 Complete JavaScript
 * Based on specification in docs/req.txt
 */

// Global state
let currentConfig = null;
let currentParameters = [];
let selectedJobId = null;
let selectedBatchJobId = null;
let allProjects = [];
let allDatasets = [];
let allWorkflows = [];
let currentProjectId = 1;
let currentWorkflowId = null;
let currentPromptId = null;  // NEW ARCHITECTURE: ID of selected prompt
let currentSelectionType = 'project'; // 'project', 'workflow', or 'prompt'
let currentExecutionTargets = null;  // NEW ARCHITECTURE: Cache of prompts/workflows for current project

// History pagination state
let singleHistoryOffset = 0;
const SINGLE_HISTORY_PAGE_SIZE = 10;
let singleHistoryHasMore = true;

let batchHistoryOffset = 0;
const BATCH_HISTORY_PAGE_SIZE = 10;
let batchHistoryHasMore = true;

// Dataset preview state
let currentPreviewDatasetId = null;

/**
 * Format date to JST (Japan Standard Time)
 * Database timestamps are stored in UTC without timezone suffix.
 * This function interprets them as UTC and converts to JST for display.
 *
 * @param {string|Date} dateInput - Date string or Date object (stored in UTC)
 * @param {boolean} includeSeconds - Whether to include seconds (default: false)
 * @returns {string} Formatted date string in JST (YYYY/MM/DD HH:MM)
 */
function formatJST(dateInput, includeSeconds = false) {
    if (!dateInput) return '-';
    try {
        let date;

        if (dateInput instanceof Date) {
            date = dateInput;
        } else {
            // Convert input to string
            let dateStr = String(dateInput);

            // Database timestamps are UTC but stored without 'Z' suffix
            // Append 'Z' to mark as UTC if no timezone info present
            // This ensures proper UTC -> JST conversion (+9 hours)
            if (!dateStr.endsWith('Z') && !dateStr.includes('+') && !dateStr.includes('-', 10)) {
                // Replace space with 'T' for ISO format if needed
                dateStr = dateStr.replace(' ', 'T');
                dateStr = dateStr + 'Z';
            }

            date = new Date(dateStr);
        }

        if (isNaN(date.getTime())) return '-';

        // Format in JST timezone (UTC+9)
        const options = {
            timeZone: 'Asia/Tokyo',
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false
        };

        if (includeSeconds) {
            options.second = '2-digit';
        }

        return date.toLocaleString('ja-JP', options);
    } catch (e) {
        return '-';
    }
}

// Global storage for CSV content (to avoid escaping issues in onclick)
const csvStorage = {};

/**
 * Store CSV content for a job
 * @param {number} jobId - The job ID
 * @param {string} csvContent - The CSV content
 */
function storeCsvContent(jobId, csvContent) {
    csvStorage[jobId] = csvContent;
}

/**
 * Copy CSV content to clipboard
 * @param {number} jobId - The job ID
 */
function copyCsvToClipboard(jobId) {
    const content = csvStorage[jobId];
    if (!content) {
        alert('CSVデータが見つかりません / CSV data not found');
        return;
    }
    navigator.clipboard.writeText(content).then(() => {
        alert('統合CSVをクリップボードにコピーしました / Merged CSV copied to clipboard');
    }).catch(err => {
        alert('コピーに失敗しました / Copy failed: ' + err.message);
    });
}

/**
 * Download CSV content as a file
 * @param {number} jobId - The job ID
 * @param {string} filename - The filename for download
 */
function downloadCsvByJobId(jobId, filename) {
    const content = csvStorage[jobId];
    if (!content) {
        alert('CSVデータが見つかりません / CSV data not found');
        return;
    }
    try {
        // Add BOM for Excel compatibility with Japanese characters
        const bom = '\uFEFF';
        const blob = new Blob([bom + content], { type: 'text/csv;charset=utf-8;' });

        // Create download link
        const link = document.createElement('a');
        const url = URL.createObjectURL(blob);
        link.setAttribute('href', url);
        link.setAttribute('download', filename);
        link.style.visibility = 'hidden';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    } catch (e) {
        alert('ダウンロードに失敗しました / Download failed: ' + e.message);
    }
}

/**
 * Legacy download function for backward compatibility
 * @param {string} csvContent - The CSV content (escaped with \n for newlines)
 * @param {string} filename - The filename for download
 */
function downloadCsv(csvContent, filename) {
    try {
        // Unescape newlines and single quotes
        const unescapedContent = csvContent.replace(/\\n/g, '\n').replace(/\\'/g, "'");

        // Add BOM for Excel compatibility with Japanese characters
        const bom = '\uFEFF';
        const blob = new Blob([bom + unescapedContent], { type: 'text/csv;charset=utf-8;' });

        // Create download link
        const link = document.createElement('a');
        const url = URL.createObjectURL(blob);
        link.setAttribute('href', url);
        link.setAttribute('download', filename);
        link.style.visibility = 'hidden';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    } catch (e) {
        alert('ダウンロードに失敗しました / Download failed: ' + e.message);
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    setupTabNavigation();
    loadInitialData();
    setupEventListeners();
});

/**
 * Setup tab navigation
 * Specification: docs/req.txt section 4.1
 */
function setupTabNavigation() {
    const tabButtons = document.querySelectorAll('.tab-button');
    const tabContents = document.querySelectorAll('.tab-content');

    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            const targetTab = button.getAttribute('data-tab');

            // Remove active class from all
            tabButtons.forEach(btn => btn.classList.remove('active'));
            tabContents.forEach(content => content.classList.remove('active'));

            // Add active class to clicked
            button.classList.add('active');
            document.getElementById(`tab-${targetTab}`).classList.add('active');

            // Load tab-specific data
            loadTabData(targetTab);
        });
    });
}

/**
 * Load initial data for all tabs
 */
async function loadInitialData() {
    try {
        // Load projects first (this also sets default project and loads config)
        await loadProjects();

        // Load settings and models
        await loadSettings();

        // Load datasets
        await loadDatasets();

        // Load available models
        await loadAvailableModels();

        // Note: loadConfig() is now called from updateProjectSelects() after setting the default project
        // This ensures currentProjectId matches the selected dropdown value
    } catch (error) {
        // Initialization error - silently continue
    }
}

/**
 * Load data when tab is switched
 */
function loadTabData(tabName) {
    switch (tabName) {
        case 'single':
            // NEW ARCHITECTURE: If a prompt/workflow is already selected, state is preserved
            // Don't reload as it would overwrite the selected prompt's config
            if (currentSelectionType === 'prompt' && currentPromptId) {
                // Already loaded, nothing to do
            } else if (currentSelectionType === 'workflow' && currentWorkflowId) {
                // Workflow already loaded
            } else if (currentProjectId) {
                // Reload execution targets which will auto-select first prompt
                loadExecutionTargets(currentProjectId);
            } else {
                // Fallback to old behavior
                loadConfig();
            }
            break;
        case 'batch':
            loadBatchJobs();
            break;
        case 'workflows':
            initWorkflowTab();
            break;
        case 'projects':
            loadProjects();
            break;
        case 'settings':
            loadSettings();
            loadAvailableModels();
            loadModelConfigurationSettings();
            loadJobParallelism();
            loadTextFileExtensions();
            break;
        case 'datasets':
            loadDatasets();
            break;
    }
}

/**
 * Setup all event listeners
 */
function setupEventListeners() {
    // Single execution
    document.getElementById('btn-send-once')?.addEventListener('click', () => executePrompt(1));
    document.getElementById('btn-send-repeat')?.addEventListener('click', () => {
        const repeat = parseInt(document.getElementById('repeat-count').value);
        executePrompt(repeat);
    });
    document.getElementById('single-project-select')?.addEventListener('change', onProjectChange);
    document.getElementById('single-target-select')?.addEventListener('change', onExecutionTargetChange);  // NEW ARCHITECTURE
    document.getElementById('btn-edit-prompt')?.addEventListener('click', showEditPromptModal);
    document.getElementById('btn-reload-single-history')?.addEventListener('click', async () => {
        const projectId = document.getElementById('single-project-select').value;
        if (projectId) {
            await loadConfig(parseInt(projectId));
            // Re-select the previously selected job if any
            if (selectedJobId) {
                selectHistoryItem(selectedJobId);
            }
        }
    });

    // Batch execution
    document.getElementById('btn-batch-execute')?.addEventListener('click', executeBatch);
    document.getElementById('batch-project-select')?.addEventListener('change', onBatchProjectChange);
    document.getElementById('btn-batch-edit-prompt')?.addEventListener('click', showBatchEditPromptModal);
    document.getElementById('btn-reload-batch-history')?.addEventListener('click', async () => {
        const selectValue = document.getElementById('batch-project-select').value;
        if (selectValue) {
            const parsed = parseSelectValue(selectValue);
            if (parsed && parsed.type === 'project' && parsed.id) {
                await loadBatchJobHistory(parsed.id);
                // Re-select the previously selected batch job if any
                if (selectedBatchJobId) {
                    selectBatchJob(selectedBatchJobId);
                }
            }
        }
    });

    // Projects
    document.getElementById('btn-create-project')?.addEventListener('click', showCreateProjectModal);

    // Datasets
    document.getElementById('btn-import-dataset')?.addEventListener('click', showImportDatasetModal);

    // Settings
    document.getElementById('btn-save-default-model')?.addEventListener('click', saveDefaultModel);
    document.getElementById('btn-save-default-project')?.addEventListener('click', saveDefaultProject);
    document.getElementById('param-model-select')?.addEventListener('change', loadModelParameters);
    document.getElementById('btn-save-model-params')?.addEventListener('click', saveModelParameters);
    document.getElementById('btn-reset-model-params')?.addEventListener('click', resetModelParameters);

    // Job execution settings
    document.getElementById('btn-save-parallelism')?.addEventListener('click', saveJobParallelism);

    // Text file extensions buttons
    document.getElementById('btn-save-text-extensions')?.addEventListener('click', saveTextFileExtensions);
    document.getElementById('btn-reset-text-extensions')?.addEventListener('click', resetTextFileExtensions);

    // Job cancellation buttons
    document.getElementById('btn-stop-single')?.addEventListener('click', cancelSingleJob);
    document.getElementById('btn-stop-batch')?.addEventListener('click', cancelBatchJob);

    // Modal overlay click - DO NOT close on outside click (user requested)
    // Removed event listener to prevent accidental modal close
}

// ========== SINGLE EXECUTION TAB ==========

/**
 * Load configuration for single execution
 * Specification: docs/req.txt section 3.2 step 2
 */
async function loadConfig(projectId = null) {
    try {
        // Use provided projectId or currentProjectId, fallback to project 1
        const pid = projectId || currentProjectId || 1;

        // Reset pagination state for single execution history
        singleHistoryOffset = 0;
        singleHistoryHasMore = true;

        // Get project details
        const projectResponse = await fetch(`/api/projects/${pid}`);
        if (!projectResponse.ok) throw new Error(`Failed to load project ${pid}`);
        const project = await projectResponse.json();

        // Get single-type jobs for this project (first page only)
        const jobsResponse = await fetch(`/api/projects/${pid}/jobs?limit=${SINGLE_HISTORY_PAGE_SIZE}&offset=0&job_type=single`);
        if (!jobsResponse.ok) throw new Error(`Failed to load jobs for project ${pid}`);
        const singleJobs = await jobsResponse.json();

        // Check if there might be more jobs
        singleHistoryHasMore = singleJobs.length >= SINGLE_HISTORY_PAGE_SIZE;
        singleHistoryOffset = singleJobs.length;

        // Use parameters from API (parsed by backend)
        const parameters = project.parameters || [];

        // Build config object compatible with existing code
        currentConfig = {
            project_id: project.id,
            project_name: project.name,
            prompt_template: project.prompt_template,
            parameters: parameters,
            recent_jobs: singleJobs,
            available_models: ["azure-gpt-4.1", "openai-gpt-4.1-nano"]
        };

        renderSingleExecutionTab();
    } catch (error) {
        showStatus('設定の読み込みに失敗しました / Failed to load configuration', 'error');
    }
}

function renderSingleExecutionTab() {
    // Render prompt template
    document.getElementById('prompt-template').textContent = currentConfig.prompt_template;

    // Render parameters
    currentParameters = currentConfig.parameters;
    renderParameterInputs();

    // Render history
    renderHistory(currentConfig.recent_jobs);
}

/**
 * Load configuration for workflow execution
 * Workflow shows combined prompt templates and parameters from all steps
 * Input parameters = Step1's prompt parameters + workflow input mapping parameters
 * @param {number} workflowId - Workflow ID
 */
async function loadWorkflowConfig(workflowId) {
    try {
        // Reset pagination state for single execution history
        singleHistoryOffset = 0;
        singleHistoryHasMore = true;

        // Get workflow details
        const workflowResponse = await fetch(`/api/workflows/${workflowId}`);
        if (!workflowResponse.ok) throw new Error(`Failed to load workflow ${workflowId}`);
        const workflow = await workflowResponse.json();

        // Get workflow jobs for history
        const jobsResponse = await fetch(`/api/workflows/${workflowId}/jobs?limit=${SINGLE_HISTORY_PAGE_SIZE}`);
        const workflowJobs = jobsResponse.ok ? await jobsResponse.json() : [];

        // Get first step's prompt to determine input parameters
        let firstStepPrompt = null;
        let parameters = [];
        const seenParams = new Set();

        if (workflow.steps && workflow.steps.length > 0) {
            const firstStep = workflow.steps[0];

            // New architecture: Get parameters from prompt using execution-targets API
            if (firstStep.prompt_id) {
                const targetsResponse = await fetch(`/api/projects/${firstStep.project_id}/execution-targets`);
                if (targetsResponse.ok) {
                    const targets = await targetsResponse.json();
                    firstStepPrompt = targets.prompts?.find(p => p.id === firstStep.prompt_id);
                    if (firstStepPrompt) {
                        // Add Step1's prompt parameters
                        for (const param of (firstStepPrompt.parameters || [])) {
                            if (!seenParams.has(param.name)) {
                                seenParams.add(param.name);
                                parameters.push(param);
                            }
                        }
                    }
                }
            }

            // Fallback: Old architecture - get from project's latest revision
            if (!firstStepPrompt) {
                const projectResponse = await fetch(`/api/projects/${firstStep.project_id}`);
                if (projectResponse.ok) {
                    const project = await projectResponse.json();
                    for (const param of (project.parameters || [])) {
                        if (!seenParams.has(param.name)) {
                            seenParams.add(param.name);
                            parameters.push(param);
                        }
                    }
                }
            }

            // Extract parameters from workflow step input mappings
            // Pattern: {{PARAM_NAME:TYPE}} that are NOT references like {{input.xxx}} or {{stepN.xxx}}
            for (const step of workflow.steps) {
                if (step.input_mapping) {
                    const mappingStr = typeof step.input_mapping === 'string'
                        ? step.input_mapping
                        : JSON.stringify(step.input_mapping);

                    // Find {{PARAM_NAME:TYPE}} patterns (NOT {{input.xxx}} or {{stepN_xxx}})
                    const regex = /\{\{([^}.]+):([^}]+)\}\}/g;
                    let match;
                    while ((match = regex.exec(mappingStr)) !== null) {
                        const paramName = match[1].trim();
                        const paramType = match[2].trim().toUpperCase();

                        // Skip if it's a reference like input.xxx or stepN.xxx
                        if (paramName.includes('.') || paramName.match(/^step\d+/i)) {
                            continue;
                        }

                        if (!seenParams.has(paramName)) {
                            seenParams.add(paramName);
                            parameters.push({
                                name: paramName,
                                type: paramType,
                                required: false  // Workflow input mapping params are optional
                            });
                        }
                    }
                }
            }
        }

        // Build combined prompt template display
        let combinedPrompt = `=== ワークフロー: ${workflow.name} ===\n`;
        combinedPrompt += `説明: ${workflow.description || '(なし)'}\n`;
        combinedPrompt += `ステップ数: ${workflow.steps.length}\n\n`;

        for (const step of workflow.steps) {
            combinedPrompt += `--- Step ${step.step_order}: ${step.step_name} ---\n`;
            combinedPrompt += `プロジェクト: ${step.project_name}\n`;
            if (step.input_mapping) {
                combinedPrompt += `入力マッピング: ${JSON.stringify(step.input_mapping)}\n`;
            }
            combinedPrompt += '\n';
        }

        // Build config object
        const firstStep = workflow.steps && workflow.steps.length > 0 ? workflow.steps[0] : null;
        currentConfig = {
            workflow_id: workflow.id,
            workflow_name: workflow.name,
            project_id: firstStep ? firstStep.project_id : null,
            project_name: firstStep ? firstStep.project_name : workflow.name,
            prompt_template: combinedPrompt,
            parameters: parameters,
            recent_jobs: workflowJobs.map(j => ({
                id: j.id,
                workflow_id: j.workflow_id,
                job_type: 'workflow',
                status: j.status,
                input_params: j.input_params,
                model_name: j.model_name,
                created_at: j.created_at,
                turnaround_ms: j.turnaround_ms
            })),
            available_models: ["azure-gpt-4.1", "openai-gpt-4.1-nano"],
            is_workflow: true
        };

        renderSingleExecutionTab();

        // Update history display to show workflow-specific jobs
        renderWorkflowHistory(workflowJobs);

    } catch (error) {
        console.error('Failed to load workflow config:', error);
        showStatus('ワークフローの読み込みに失敗しました / Failed to load workflow configuration', 'error');
    }
}

/**
 * Render workflow execution history
 * @param {Array} jobs - Workflow jobs
 */
function renderWorkflowHistory(jobs) {
    const container = document.getElementById('history-list');
    if (!container) return;

    if (!jobs || jobs.length === 0) {
        container.innerHTML = '<div class="history-item">履歴がありません / No history</div>';
        return;
    }

    container.innerHTML = jobs.map(job => `
        <div class="history-item ${selectedJobId === job.id ? 'selected' : ''}"
             onclick="selectWorkflowJob(${job.id})">
            <div class="history-item-header">
                <span class="history-item-id">WF-Job #${job.id}</span>
                <span class="history-item-status status-${job.status}">${job.status}</span>
            </div>
            <div class="history-item-time">${formatJST(job.created_at)}</div>
            <div class="history-item-model">${job.model_name || 'default'}</div>
            ${job.turnaround_ms ? `<div class="history-item-time">${job.turnaround_ms}ms</div>` : ''}
        </div>
    `).join('');
}

/**
 * Select and display workflow job results
 * @param {number} jobId - Workflow job ID
 */
async function selectWorkflowJob(jobId) {
    selectedJobId = jobId;

    // Update selection in history list
    document.querySelectorAll('.history-item').forEach(item => {
        item.classList.remove('selected');
        if (item.querySelector(`[onclick*="selectWorkflowJob(${jobId})"]`) || item.getAttribute('onclick')?.includes(`selectWorkflowJob(${jobId})`)) {
            item.classList.add('selected');
        }
    });

    // Highlight the selected item
    const historyItems = document.querySelectorAll('.history-item');
    historyItems.forEach(item => {
        if (item.getAttribute('onclick')?.includes(`selectWorkflowJob(${jobId})`)) {
            item.classList.add('selected');
        }
    });

    try {
        const response = await fetch(`/api/workflow-jobs/${jobId}`);
        if (!response.ok) throw new Error('Failed to fetch workflow job');
        const job = await response.json();

        // Populate input form with the job's input params
        if (job.input_params) {
            const params = typeof job.input_params === 'string'
                ? JSON.parse(job.input_params)
                : job.input_params;
            populateInputForm(params);
        }

        displayWorkflowJobResults(job);
    } catch (error) {
        console.error('Failed to load workflow job:', error);
        showStatus('ワークフロージョブの読み込みに失敗しました / Failed to load workflow job', 'error');
    }
}

/**
 * Display workflow job results
 * @param {Object} job - Workflow job data
 */
function displayWorkflowJobResults(job) {
    const container = document.getElementById('result-raw');
    const parsedContainer = document.getElementById('result-parsed');

    if (!container) return;

    // Build raw output showing all step results
    let rawOutput = `=== ワークフロージョブ #${job.id} ===\n`;
    rawOutput += `ステータス: ${job.status}\n`;
    rawOutput += `モデル: ${job.model_name || 'default'}\n`;
    rawOutput += `作成日時: ${formatJST(job.created_at)}\n`;
    if (job.turnaround_ms) {
        rawOutput += `処理時間: ${job.turnaround_ms}ms\n`;
    }
    rawOutput += '\n';

    if (job.step_results && job.step_results.length > 0) {
        for (const step of job.step_results) {
            rawOutput += `--- Step ${step.step_order}: ${step.step_name} (${step.status}) ---\n`;
            if (step.output_fields) {
                rawOutput += JSON.stringify(step.output_fields, null, 2) + '\n';
            }
            if (step.error_message) {
                rawOutput += `エラー: ${step.error_message}\n`;
            }
            if (step.turnaround_ms) {
                rawOutput += `処理時間: ${step.turnaround_ms}ms\n`;
            }
            rawOutput += '\n';
        }
    }

    container.textContent = rawOutput;

    // Display merged output in parsed section
    if (parsedContainer && job.merged_output) {
        parsedContainer.innerHTML = `<pre>${escapeHtmlGlobal(JSON.stringify(job.merged_output, null, 2))}</pre>`;
    } else if (parsedContainer) {
        parsedContainer.innerHTML = '<span class="no-data">統合結果なし / No merged output</span>';
    }
}

function renderParameterInputs() {
    const container = document.getElementById('parameter-inputs');
    if (!container) return;

    container.innerHTML = '';

    currentParameters.forEach(param => {
        const group = document.createElement('div');
        group.className = 'param-group';

        const label = document.createElement('label');
        label.setAttribute('for', `param-${param.name}`);

        // Add required asterisk if parameter is required
        if (param.required) {
            label.innerHTML = `${param.name} (${param.type}) <span class="required-asterisk">*</span>`;
        } else {
            label.textContent = `${param.name} (${param.type})`;
        }

        let input;
        if (param.html_type === 'textarea') {
            input = document.createElement('textarea');
            input.rows = param.rows || 5;  // Default to 5 rows
            input.id = `param-${param.name}`;
            input.name = param.name;
            input.required = param.required;

            // Set default value if provided
            if (param.default) {
                input.value = param.default;
            }

            group.appendChild(label);
            group.appendChild(input);
            container.appendChild(group);
            return; // Skip the default input append
        } else if (param.html_type === 'file') {
            // Enhanced FILE input with preview, info, and reset button
            input = document.createElement('input');
            input.type = 'file';
            input.id = `param-${param.name}`;
            input.name = param.name;
            input.required = param.required;

            if (param.accept) {
                input.accept = param.accept;
            }

            // Create wrapper for file input with drag & drop support
            const fileWrapper = document.createElement('div');
            fileWrapper.className = 'file-input-wrapper';
            fileWrapper.innerHTML = `
                <div class="file-drop-zone" id="drop-zone-${param.name}">
                    <div class="file-drop-icon">📁</div>
                    <div class="file-drop-text">クリックまたはドラッグ&ドロップ<br>Click or drag & drop image here</div>
                </div>
                <div class="file-info-container" id="file-info-${param.name}" style="display: none;">
                    <div class="file-info-header">
                        <span class="file-info-name" id="file-name-${param.name}"></span>
                        <button type="button" class="btn-file-clear" id="clear-${param.name}">✕ クリア</button>
                    </div>
                    <div class="file-info-details">
                        <span class="file-info-size" id="file-size-${param.name}"></span>
                        <span class="file-info-type" id="file-type-${param.name}"></span>
                    </div>
                </div>
                <div class="image-preview-container" id="preview-container-${param.name}" style="display: none;">
                    <img class="image-preview" id="preview-${param.name}" alt="Preview">
                </div>
            `;

            // Insert hidden file input
            fileWrapper.insertBefore(input, fileWrapper.firstChild);

            group.appendChild(label);
            group.appendChild(fileWrapper);
            container.appendChild(group);

            // Setup file input handlers after DOM insertion
            setupFileInputHandlers(param.name);
            return; // Skip the default input append
        } else {
            input = document.createElement('input');
            input.type = param.html_type;

            // Set accept attribute for file inputs
            if (param.accept) {
                input.accept = param.accept;
            }

            // Set placeholder for text inputs
            if (param.placeholder) {
                input.placeholder = param.placeholder;
            }

            // Set default value if provided
            if (param.default) {
                input.value = param.default;
            }
        }

        input.id = `param-${param.name}`;
        input.name = param.name;
        input.required = param.required;

        group.appendChild(label);
        group.appendChild(input);
        container.appendChild(group);
    });
}

function renderHistory(jobs, append = false) {
    const container = document.getElementById('history-list');
    if (!container) return;

    // Always remove existing "Load more" link first when appending
    if (append) {
        const existingLoadMore = container.querySelector('.load-more-link');
        if (existingLoadMore) {
            existingLoadMore.remove();
        }
    }

    // Handle empty jobs
    if (!jobs || jobs.length === 0) {
        if (!append) {
            container.innerHTML = '<p class="info">履歴がありません / No history</p>';
        }
        // When append mode with no new items, just update Load More button state
        // (already removed above, add back only if hasMore is still true)
        if (append && singleHistoryHasMore) {
            container.insertAdjacentHTML('beforeend', `
                <div class="load-more-link" onclick="loadMoreSingleHistory()">
                    さらに表示 / Load more...
                </div>
            `);
        }
        return;
    }

    const jobsHtml = jobs.map(job => {
        const createdAt = formatJST(job.created_at);
        const finishedAt = formatJST(job.finished_at);
        const turnaround = job.turnaround_ms ? `${(job.turnaround_ms / 1000).toFixed(1)}s` : 'N/A';
        const itemCount = job.items ? job.items.length : 0;
        const modelName = job.model_name || '-';
        const promptName = job.prompt_name || '-';

        // Show delete button for pending/running jobs
        const canDelete = job.status === 'pending' || job.status === 'running';
        const deleteBtn = canDelete ?
            `<button class="delete-job-btn" onclick="event.stopPropagation(); deleteJob(${job.id}, 'single')" title="ジョブを削除">🗑️</button>` : '';

        return `
            <div class="history-item" data-job-id="${job.id}" onclick="selectHistoryItem(${job.id})">
                <div class="job-header">
                    <div class="job-id">Job #${job.id} (${itemCount} items)</div>
                    ${deleteBtn}
                </div>
                <div class="prompt-info">🎯 ${promptName}</div>
                <div class="timestamp">実行: ${createdAt}</div>
                <div class="timestamp">完了: ${finishedAt}</div>
                <div class="turnaround">モデル: ${modelName} | 実行時間: ${turnaround}</div>
                <span class="status ${job.status}">${job.status}</span>
            </div>
        `;
    }).join('');

    // Add "Load more" link if there are more jobs
    const loadMoreHtml = singleHistoryHasMore ? `
        <div class="load-more-link" onclick="loadMoreSingleHistory()">
            さらに表示 / Load more...
        </div>
    ` : '';

    if (append) {
        container.insertAdjacentHTML('beforeend', jobsHtml + loadMoreHtml);
    } else {
        container.innerHTML = jobsHtml + loadMoreHtml;
    }
}

let singleHistoryLoading = false;

async function loadMoreSingleHistory() {
    // Prevent duplicate clicks while loading
    if (singleHistoryLoading) return;
    singleHistoryLoading = true;

    // Update button to show loading state
    const loadMoreBtn = document.querySelector('#history-list .load-more-link');
    if (loadMoreBtn) {
        loadMoreBtn.textContent = '読み込み中... / Loading...';
        loadMoreBtn.style.pointerEvents = 'none';
    }

    try {
        const pid = currentProjectId || 1;

        // Fetch next page of single-type jobs
        const response = await fetch(`/api/projects/${pid}/jobs?limit=${SINGLE_HISTORY_PAGE_SIZE}&offset=${singleHistoryOffset}&job_type=single`);
        if (!response.ok) throw new Error('Failed to load more jobs');
        const singleJobs = await response.json();

        // Update pagination state BEFORE rendering
        // No more items if we got fewer than requested
        singleHistoryHasMore = singleJobs.length >= SINGLE_HISTORY_PAGE_SIZE;
        singleHistoryOffset += singleJobs.length;

        // Append to existing history (or update Load More button state)
        renderHistory(singleJobs, true);
    } catch (error) {
        showStatus('履歴の読み込みに失敗しました / Failed to load more history', 'error');
    } finally {
        singleHistoryLoading = false;
    }
}

function selectHistoryItem(jobId) {
    selectedJobId = jobId;

    document.querySelectorAll('.history-item').forEach(item => {
        if (parseInt(item.dataset.jobId) === jobId) {
            item.classList.add('selected');
        } else {
            item.classList.remove('selected');
        }
    });

    // Safely access recent_jobs with null check
    const recentJobs = currentConfig?.recent_jobs || [];
    const job = recentJobs.find(j => j.id === jobId);
    if (job) {
        displayJobResults(job);
        if (job.items && job.items.length > 0) {
            const params = JSON.parse(job.items[0].input_params);
            populateInputForm(params);
        }
    }
}

function displayJobResults(job, targetContainer = null) {
    // Accept container as parameter to avoid getElementById conflicts between tabs
    // When called from batch tab, container is passed directly
    // When called from single tab (or no param), use default #results-area
    const container = targetContainer || document.getElementById('results-area');

    if (!container) {
        return;
    }

    if (!job.items || job.items.length === 0) {
        container.innerHTML = '<p class="info">結果がありません / No results</p>';
        return;
    }

    // Helper function to escape HTML
    function escapeHtml(unsafe) {
        if (!unsafe) return '';
        return String(unsafe)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    // Display progress summary for batch jobs
    let progressSection = '';
    if (job.job_type === 'batch' && job.items && job.items.length > 0) {
        const total = job.items.length;
        const completed = job.items.filter(item => item.status === 'done').length;
        const errors = job.items.filter(item => item.status === 'error').length;
        const pending = job.items.filter(item => item.status === 'pending').length;
        const running = job.items.filter(item => item.status === 'running').length;
        const progressPercent = Math.round((completed + errors) / total * 100);

        progressSection = `
            <div class="result-item" style="background: linear-gradient(135deg, #3498db 0%, #2980b9 100%); color: white; border-left: 5px solid #2ecc71;">
                <div class="item-header" style="color: white; font-size: 1.2rem;">
                    📊 バッチ実行進捗 / Batch Execution Progress
                </div>
                <div style="margin-top: 1rem; background: white; color: #2c3e50; padding: 1rem; border-radius: 4px;">
                    <div style="font-size: 1.1rem; margin-bottom: 0.5rem;">
                        <strong>進捗: ${completed + errors} / ${total} 件完了 (${progressPercent}%)</strong>
                    </div>
                    <div style="display: flex; gap: 1rem; margin-top: 0.5rem; flex-wrap: wrap;">
                        <span style="color: #27ae60;">✓ 成功: ${completed}件</span>
                        <span style="color: #e74c3c;">✗ エラー: ${errors}件</span>
                        ${pending > 0 ? `<span style="color: #95a5a6;">⏳ 待機中: ${pending}件</span>` : ''}
                        ${running > 0 ? `<span style="color: #3498db;">▶ 実行中: ${running}件</span>` : ''}
                    </div>
                    <div style="margin-top: 1rem; background: #ecf0f1; border-radius: 4px; height: 20px; overflow: hidden;">
                        <div style="background: linear-gradient(90deg, #27ae60 0%, #2ecc71 100%); height: 100%; width: ${progressPercent}%; transition: width 0.3s ease;"></div>
                    </div>
                </div>
            </div>
        `;
    }

    // Display merged CSV output for batch jobs, repeated single executions, and single with header
    let mergedCsvSection = '';
    if (job.merged_csv_output) {
        // Store CSV content in global storage to avoid escaping issues
        storeCsvContent(job.id, job.merged_csv_output);
        const isBatch = job.job_type === 'batch';
        const itemCount = job.items ? job.items.length : 0;
        let title;
        if (isBatch) {
            title = 'バッチ実行結果 (CSV統合) / Batch Results (Merged CSV)';
        } else if (itemCount > 1) {
            title = 'n回送信結果 (CSV統合) / Repeated Execution Results (Merged CSV)';
        } else {
            title = 'パーサー結果 (CSV) / Parsed Results (CSV)';
        }
        const csvFilename = `job_${job.id}_results_${new Date().toISOString().slice(0,10)}.csv`;
        // Escape HTML entities for display in <pre> tag
        const displayCsv = escapeHtml(job.merged_csv_output);
        mergedCsvSection = `
            <div class="result-item" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border-left: 5px solid #f39c12;">
                <div class="item-header" style="color: white; font-size: 1.2rem;">
                    📊 ${title}
                </div>
                <div style="margin-top: 1rem; background: white; color: #2c3e50; padding: 1rem; border-radius: 4px;">
                    <div class="response-box" style="background-color: #f8f9fa; font-family: 'Courier New', monospace; max-height: 400px; overflow-y: auto;">
                        <pre style="white-space: pre-wrap; word-wrap: break-word;">${displayCsv}</pre>
                    </div>
                    <div style="margin-top: 1rem; display: flex; gap: 0.5rem; flex-wrap: wrap;">
                        <button onclick="copyCsvToClipboard(${job.id})"
                                style="padding: 0.5rem 1.5rem; background: #27ae60; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold;">
                            📋 統合CSVをコピー / Copy Merged CSV
                        </button>
                        <button onclick="downloadCsvByJobId(${job.id}, 'job_${job.id}_results_${new Date().toISOString().slice(0,10)}.csv')"
                                style="padding: 0.5rem 1.5rem; background: #3498db; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold;">
                            💾 CSVをダウンロード / Download CSV
                        </button>
                    </div>
                    <p style="margin-top: 1rem; color: #7f8c8d; font-size: 0.9rem;">
                        ${job.items.length}件の実行結果を統合しました / Merged ${job.items.length} execution results
                    </p>
                </div>
            </div>
            <h3 style="margin-top: 2rem; color: #34495e; border-bottom: 2px solid #ecf0f1; padding-bottom: 0.5rem;">
                個別実行結果 / Individual Results
            </h3>
        `;
    }

    const itemsHtml = job.items.map((item, index) => {
        try {
            const turnaround = item.turnaround_ms ? `${item.turnaround_ms}ms` : 'N/A';
            let content;

            if (item.status === 'error') {
                content = `<div class="error">Error: ${escapeHtml(item.error_message || 'Unknown error')}</div>`;
            } else {
            // Parse the parsed_response if it exists
            let parsedContent = '';
            if (item.parsed_response) {
                try {
                    const parsed = JSON.parse(item.parsed_response);
                    if (parsed.parsed === false) {
                        // No parser configured
                        parsedContent = '';
                    } else {
                        // Check if CSV output is available (priority display)
                        if (parsed.csv_output) {
                            // Store item CSV in global storage with unique key
                            const itemCsvKey = `item_${job.id}_${index}`;
                            storeCsvContent(itemCsvKey, parsed.csv_output);
                            parsedContent = `
                                <div style="margin-top: 1rem;">
                                    <h4 style="color: #27ae60; margin-bottom: 0.5rem;">📊 パーサー結果 (CSV形式) / Parsed Results (CSV):</h4>
                                    <div class="response-box" style="background-color: #e8f8f5; font-family: 'Courier New', monospace;">
                                        <pre style="white-space: pre-wrap; word-wrap: break-word;">${escapeHtml(parsed.csv_output)}</pre>
                                    </div>
                                    <button onclick="copyCsvToClipboard('${itemCsvKey}')"
                                            style="margin-top: 0.5rem; padding: 0.5rem 1rem; background: #27ae60; color: white; border: none; border-radius: 4px; cursor: pointer;">
                                        📋 CSVをコピー / Copy CSV
                                    </button>
                                    <details style="margin-top: 0.5rem;">
                                        <summary style="cursor: pointer; color: #7f8c8d;">フィールド詳細を表示 / Show Field Details</summary>
                                        <pre style="margin-top: 0.5rem;">${escapeHtml(JSON.stringify(parsed.fields || {}, null, 2))}</pre>
                                    </details>
                                </div>
                            `;
                        } else {
                            // Check if this is score data (many numeric fields)
                            const fields = parsed.fields || parsed;
                            const isScoreData = Object.values(fields).every(v =>
                                typeof v === 'number' || (typeof v === 'string' && !isNaN(v))
                            );

                            if (isScoreData && Object.keys(fields).length > 5) {
                                // Display as compact table for scores
                                const scoreRows = Object.entries(fields).map(([key, value]) =>
                                    `<span style="display: inline-block; margin: 0.2rem 0.5rem; padding: 0.2rem 0.5rem; background: white; border-radius: 3px;"><strong>${key}:</strong> ${value}</span>`
                                ).join('');

                                parsedContent = `
                                    <div style="margin-top: 1rem;">
                                        <h4 style="color: #27ae60; margin-bottom: 0.5rem;">📊 パーサー結果 (スコア一覧) / Parsed Results (Scores):</h4>
                                        <div class="response-box" style="background-color: #e8f8f5; line-height: 2;">
                                            ${scoreRows}
                                        </div>
                                        <details style="margin-top: 0.5rem;">
                                            <summary style="cursor: pointer; color: #7f8c8d;">JSON形式で表示 / Show as JSON</summary>
                                            <pre style="margin-top: 0.5rem;">${JSON.stringify(fields, null, 2)}</pre>
                                        </details>
                                    </div>
                                `;
                            } else {
                                // Display as regular JSON
                                parsedContent = `
                                    <div style="margin-top: 1rem;">
                                        <h4 style="color: #27ae60; margin-bottom: 0.5rem;">📊 パーサー結果 / Parsed Results:</h4>
                                        <div class="response-box" style="background-color: #e8f8f5;">
                                            <pre>${JSON.stringify(fields, null, 2)}</pre>
                                        </div>
                                    </div>
                                `;
                            }
                        }
                    }
                } catch (e) {
                    parsedContent = `<div style="color: #e74c3c; margin-top: 1rem;">パーサーエラー / Parser error: ${e.message}</div>`;
                }
            }

            content = `
                <div>
                    <h4 style="color: #34495e; margin-bottom: 0.5rem;">📤 送信プロンプト / Sent Prompt:</h4>
                    <div class="response-box" style="background-color: #f8f9fa; max-height: 300px; overflow-y: auto;">
                        <pre>${escapeHtml(item.raw_prompt) || 'No prompt'}</pre>
                    </div>

                    <h4 style="color: #2c3e50; margin-top: 1rem; margin-bottom: 0.5rem;">📄 生レスポンス / Raw Response:</h4>
                    <div class="response-box">
                        <pre>${escapeHtml(item.raw_response) || 'No response'}</pre>
                    </div>
                    ${parsedContent}
                </div>
            `;
        }

            return `
                <div class="result-item">
                    <div class="item-header">Result #${index + 1} <span class="status ${item.status}">${item.status}</span></div>
                    <div class="turnaround">Turnaround: ${turnaround}</div>
                    ${content}
                </div>
            `;
        } catch (error) {
            return `
                <div class="result-item">
                    <div class="item-header">Result #${index + 1} <span class="status error">render_error</span></div>
                    <div class="error">レンダリングエラー / Rendering error: ${escapeHtml(error.message)}</div>
                </div>
            `;
        }
    }).join('');

    container.innerHTML = progressSection + mergedCsvSection + itemsHtml;
}

function populateInputForm(params) {
    Object.entries(params).forEach(([name, value]) => {
        const input = document.getElementById(`param-${name}`);
        // Skip file inputs - cannot programmatically set file input values for security reasons
        if (input && input.type !== 'file') {
            input.value = value;
        }
    });
}

async function executePrompt(repeat) {
    console.log('🚀 executePrompt called with repeat:', repeat);
    console.log('📋 currentParameters:', currentParameters);
    console.log('📂 currentProjectId:', currentProjectId);
    console.log('🎯 currentSelectionType:', currentSelectionType);

    const inputParams = {};
    let valid = true;

    // Process parameters (including FILE type)
    for (const param of currentParameters) {
        const input = document.getElementById(`param-${param.name}`);

        if (param.html_type === 'file') {
            // Handle FILE type - convert to Base64
            const hasFile = input && input.files && input.files.length > 0;

            // Check if required parameter has file
            if (param.required && !hasFile) {
                valid = false;
                showStatus(`ファイル "${param.name}" を選択してください`, 'error');
                break;
            }

            // Process file if provided
            if (hasFile) {
                try {
                    const file = input.files[0];
                    console.log(`📁 FILE parameter "${param.name}": ${file.name}, size: ${file.size} bytes`);
                    const base64 = await fileToBase64(file);
                    console.log(`📦 Base64 encoded length: ${base64.length} chars`);
                    inputParams[param.name] = base64;
                } catch (error) {
                    valid = false;
                    showStatus(`ファイル "${param.name}" の読み込みに失敗しました: ${error.message}`, 'error');
                    break;
                }
            }
        } else {
            // Handle other types (text, number, date, FILEPATH, etc.)
            const value = input ? input.value.trim() : '';

            // Check if required parameter has value
            if (param.required && !value) {
                valid = false;
                showStatus(`パラメータ "${param.name}" を入力してください`, 'error');
                break;
            }

            // Only include in params if there's a value (or if required)
            if (value || param.required) {
                inputParams[param.name] = input ? input.value : '';
            }
        }
    }

    if (!valid) return;

    const modelName = document.getElementById('model-select').value;
    const includeCsvHeader = document.getElementById('single-include-csv-header')?.checked ?? true;

    setExecutionState(true);
    showStatus('実行中... / Executing...', 'info');

    // Show stop button
    document.getElementById('btn-stop-single').style.display = 'inline-block';

    try {
        // Get model parameters from system settings
        const paramsResponse = await fetch(`/api/settings/models/${modelName}/parameters`);
        const paramsData = await paramsResponse.json();
        const modelParams = paramsData.active_parameters || {};

        // Check if we're executing a workflow, prompt, or project
        if (currentSelectionType === 'workflow' && currentWorkflowId) {
            // Workflow execution
            await executeWorkflow(inputParams, modelName, modelParams.temperature || 0.7, repeat);
        } else {
            // Regular prompt/project execution
            const requestBody = {
                project_id: currentProjectId || 1,
                input_params: inputParams,
                repeat: repeat,
                model_name: modelName,
                include_csv_header: includeCsvHeader,
                ...modelParams  // Include all model parameters from system settings
            };

            // NEW ARCHITECTURE: Add prompt_id if executing a specific prompt
            if (currentSelectionType === 'prompt' && currentPromptId) {
                requestBody.prompt_id = currentPromptId;
            }

            console.log('🚀 Sending request to /api/run/single');
            console.log('📊 Request body size:', JSON.stringify(requestBody).length, 'chars');

            const response = await fetch('/api/run/single', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(requestBody)
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Execution failed');
            }

            const result = await response.json();

            // Store job ID for cancellation
            currentSingleJobId = result.job_id;

            if (result.success) {
                showStatus(`ジョブ開始！ ${result.message}`, 'info');
                displayJobResults(result.job);

                // Restore execution state (but keep stop button visible)
                setExecutionState(false);

                // Start polling for job progress
                pollSingleJobProgress(result.job_id, currentProjectId);
            }
        }
    } catch (error) {
        showStatus(`エラー / Error: ${error.message}`, 'error');
        setExecutionState(false);
        // Hide stop button on error
        document.getElementById('btn-stop-single').style.display = 'none';
        currentSingleJobId = null;
    }
}

/**
 * Execute workflow
 * @param {Object} inputParams - Input parameters
 * @param {string} modelName - Model name
 * @param {number} temperature - Temperature setting
 * @param {number} repeat - Number of times to repeat (for workflows, execute sequentially)
 */
async function executeWorkflow(inputParams, modelName, temperature, repeat) {
    console.log(`🔄 Executing workflow ${currentWorkflowId} with repeat=${repeat}`);

    for (let i = 0; i < repeat; i++) {
        if (repeat > 1) {
            showStatus(`ワークフロー実行中... (${i + 1}/${repeat})`, 'info');
        }

        const requestBody = {
            input_params: inputParams,
            model_name: modelName,
            temperature: temperature
        };

        console.log(`🚀 Sending request to /api/workflows/${currentWorkflowId}/run`);

        const response = await fetch(`/api/workflows/${currentWorkflowId}/run`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(requestBody)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Workflow execution failed');
        }

        const result = await response.json();
        console.log('📥 Workflow job created:', result);

        // Start polling for workflow job progress
        pollWorkflowJobProgress(result.id, currentWorkflowId);

        // If this is not the last iteration, wait a bit before the next one
        if (i < repeat - 1) {
            await new Promise(resolve => setTimeout(resolve, 500));
        }
    }

    showStatus(`ワークフロージョブ開始！`, 'info');
    setExecutionState(false);
}

// Poll workflow job progress until completion
let workflowPollIntervalId = null;

async function pollWorkflowJobProgress(jobId, workflowId) {
    // Clear any existing polling interval
    if (workflowPollIntervalId) {
        clearInterval(workflowPollIntervalId);
    }

    // Poll every 3 seconds
    workflowPollIntervalId = setInterval(async () => {
        try {
            const response = await fetch(`/api/workflow-jobs/${jobId}`);
            if (!response.ok) {
                clearInterval(workflowPollIntervalId);
                workflowPollIntervalId = null;
                hideSingleStopButton();
                return;
            }

            const job = await response.json();

            // Update display with latest job data
            displayWorkflowJobResults(job);

            // If job is complete or error, stop polling
            if (job.status === 'done' || job.status === 'completed' || job.status === 'error') {
                clearInterval(workflowPollIntervalId);
                workflowPollIntervalId = null;
                hideSingleStopButton();

                if (job.status === 'done' || job.status === 'completed') {
                    showStatus('ワークフロー完了！', 'success');
                } else {
                    showStatus('ワークフローでエラーが発生しました', 'error');
                }

                // Refresh workflow history
                if (currentSelectionType === 'workflow' && currentWorkflowId) {
                    await loadWorkflowConfig(currentWorkflowId);
                }
            }
        } catch (error) {
            console.error('Failed to poll workflow job:', error);
            clearInterval(workflowPollIntervalId);
            workflowPollIntervalId = null;
            hideSingleStopButton();
        }
    }, 3000);
}

// Poll single job progress until completion
let singlePollIntervalId = null;

async function pollSingleJobProgress(jobId, projectId) {
    // Clear any existing polling interval
    if (singlePollIntervalId) {
        clearInterval(singlePollIntervalId);
    }

    // Poll every 3 seconds
    singlePollIntervalId = setInterval(async () => {
        try {
            // Fetch updated job data
            const response = await fetch(`/api/projects/${projectId}/jobs`);
            const allJobs = await response.json();
            const job = allJobs.find(j => j.id === jobId);

            if (!job) {
                // Job not found, stop polling
                clearInterval(singlePollIntervalId);
                singlePollIntervalId = null;
                hideSingleStopButton();
                return;
            }

            // Update display with latest job data
            displayJobResults(job);

            // Check if job is complete (including cancelled)
            const isComplete = job.status === 'done' || job.status === 'error' || job.status === 'cancelled';
            const allItemsComplete = job.items && job.items.every(item =>
                item.status === 'done' || item.status === 'error' || item.status === 'cancelled'
            );

            if (isComplete || allItemsComplete) {
                // Job finished, stop polling
                clearInterval(singlePollIntervalId);
                singlePollIntervalId = null;
                hideSingleStopButton();

                // Show completion status
                const completedCount = job.items.filter(i => i.status === 'done').length;
                const errorCount = job.items.filter(i => i.status === 'error').length;
                showStatus(`実行完了！ ${completedCount} 成功, ${errorCount} エラー`, 'success');

                // Reload history to show final status (use new architecture)
                if (currentProjectId) {
                    await loadExecutionTargets(currentProjectId);
                } else {
                    await loadConfig();
                }
                selectHistoryItem(jobId);
            }
        } catch (error) {
            console.error('Error polling single job:', error);
            // Continue polling on error (network issue might be temporary)
        }
    }, 3000); // Poll every 3 seconds
}

function hideSingleStopButton() {
    document.getElementById('btn-stop-single').style.display = 'none';
    currentSingleJobId = null;
}

function setExecutionState(executing) {
    const btnOnce = document.getElementById('btn-send-once');
    const btnRepeat = document.getElementById('btn-send-repeat');
    if (btnOnce) btnOnce.disabled = executing;
    if (btnRepeat) btnRepeat.disabled = executing;
}

/**
 * Convert File object to Base64 string with data URL format
 * @param {File} file - The file to convert
 * @returns {Promise<string>} - Base64 encoded data URL (e.g., "data:image/jpeg;base64,...")
 */
function fileToBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();

        reader.onload = () => {
            // reader.result contains the data URL (data:image/jpeg;base64,...)
            resolve(reader.result);
        };

        reader.onerror = () => {
            reject(new Error('Failed to read file'));
        };

        // Read file as data URL (includes Base64 encoding)
        reader.readAsDataURL(file);
    });
}

/**
 * Setup event handlers for FILE type input
 * @param {string} paramName - Parameter name for the FILE input
 */
function setupFileInputHandlers(paramName) {
    const fileInput = document.getElementById(`param-${paramName}`);
    const dropZone = document.getElementById(`drop-zone-${paramName}`);
    const fileInfo = document.getElementById(`file-info-${paramName}`);
    const previewContainer = document.getElementById(`preview-container-${paramName}`);
    const preview = document.getElementById(`preview-${paramName}`);
    const fileName = document.getElementById(`file-name-${paramName}`);
    const fileSize = document.getElementById(`file-size-${paramName}`);
    const fileType = document.getElementById(`file-type-${paramName}`);
    const clearBtn = document.getElementById(`clear-${paramName}`);

    if (!fileInput || !dropZone) return;

    // Click on drop zone opens file picker
    dropZone.addEventListener('click', () => {
        fileInput.click();
    });

    // Handle file selection
    fileInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) {
            handleFileSelect(file);
        }
    });

    // Drag & drop handlers
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.add('dragover');
    });

    dropZone.addEventListener('dragleave', (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.remove('dragover');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.remove('dragover');

        const files = e.dataTransfer.files;
        if (files.length > 0) {
            fileInput.files = files;  // Update file input
            handleFileSelect(files[0]);
        }
    });

    // Clear button handler
    if (clearBtn) {
        clearBtn.addEventListener('click', (e) => {
            e.stopPropagation();  // Don't trigger drop zone click
            clearFileInput();
        });
    }

    function handleFileSelect(file) {
        // Validate file type
        const validTypes = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];
        if (!validTypes.includes(file.type)) {
            alert(`無効なファイル形式です / Invalid file type: ${file.type}\nサポート形式 / Supported: JPEG, PNG, GIF, WebP`);
            clearFileInput();
            return;
        }

        // Validate file size (20MB max)
        const maxSize = 20 * 1024 * 1024;  // 20MB
        if (file.size > maxSize) {
            alert(`ファイルサイズが大きすぎます / File too large: ${(file.size / 1024 / 1024).toFixed(2)}MB\n最大サイズ / Max size: 20MB`);
            clearFileInput();
            return;
        }

        // Show file info
        if (fileName) fileName.textContent = file.name;
        if (fileSize) fileSize.textContent = formatFileSize(file.size);
        if (fileType) fileType.textContent = file.type.split('/')[1].toUpperCase();

        // Hide drop zone, show file info
        if (dropZone) dropZone.style.display = 'none';
        if (fileInfo) fileInfo.style.display = 'block';

        // Load and show preview for images
        const reader = new FileReader();
        reader.onload = (e) => {
            if (preview) {
                preview.src = e.target.result;
                if (previewContainer) previewContainer.style.display = 'block';
            }
        };
        reader.readAsDataURL(file);
    }

    function clearFileInput() {
        // Clear file input
        fileInput.value = '';

        // Reset UI
        if (dropZone) dropZone.style.display = 'flex';
        if (fileInfo) fileInfo.style.display = 'none';
        if (previewContainer) previewContainer.style.display = 'none';
        if (preview) preview.src = '';
    }

    function formatFileSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / 1024 / 1024).toFixed(2) + ' MB';
    }
}

function showStatus(message, type) {
    console.log(`📢 showStatus: "${message}" (${type})`);
    const statusDiv = document.getElementById('execution-status');
    if (!statusDiv) {
        console.error('❌ execution-status element not found!');
        return;
    }

    statusDiv.textContent = message;
    statusDiv.className = `status-message ${type} show`;
    console.log('✅ Status displayed, className:', statusDiv.className);

    if (type === 'success') {
        setTimeout(() => statusDiv.classList.remove('show'), 5000);
    }
}

async function onProjectChange(e) {
    // Handle both event-triggered and manual calls
    let selectValue;
    if (e && e.target) {
        selectValue = e.target.value;
    } else {
        // Manual call - get from dropdown
        const singleSelect = document.getElementById('single-project-select');
        if (singleSelect) {
            selectValue = singleSelect.value;
        }
    }

    // Parse the select value to determine type
    const { type, id } = parseSelectValue(selectValue);

    if (type === 'workflow') {
        currentSelectionType = 'workflow';
        currentWorkflowId = id;
        currentProjectId = null;
        currentPromptId = null;
        await loadWorkflowConfig(id);
    } else {
        currentSelectionType = 'project';
        currentProjectId = id;
        currentWorkflowId = null;
        currentPromptId = null;

        // NEW ARCHITECTURE: Load execution targets (prompts and workflows) for this project
        await loadExecutionTargets(id);
    }
}

/**
 * NEW ARCHITECTURE: Load execution targets (prompts and workflows) for a project
 * This populates the second dropdown with prompts and workflows
 */
async function loadExecutionTargets(projectId) {
    try {
        const response = await fetch(`/api/projects/${projectId}/execution-targets`);
        if (!response.ok) {
            throw new Error('Failed to load execution targets');
        }

        currentExecutionTargets = await response.json();

        // Update the execution target selector
        updateExecutionTargetSelector(currentExecutionTargets);

        // Also load and display history for this project
        singleHistoryOffset = 0;
        singleHistoryHasMore = true;
        const jobsResponse = await fetch(`/api/projects/${projectId}/jobs?limit=${SINGLE_HISTORY_PAGE_SIZE}&offset=0&job_type=single`);
        if (jobsResponse.ok) {
            const singleJobs = await jobsResponse.json();
            singleHistoryHasMore = singleJobs.length >= SINGLE_HISTORY_PAGE_SIZE;
            singleHistoryOffset = singleJobs.length;
            renderHistory(singleJobs);
        }

        // Auto-select first prompt if available
        if (currentExecutionTargets.prompts && currentExecutionTargets.prompts.length > 0) {
            const firstPrompt = currentExecutionTargets.prompts[0];
            currentPromptId = firstPrompt.id;
            currentSelectionType = 'prompt';

            // Update selector value
            const targetSelect = document.getElementById('single-target-select');
            if (targetSelect) {
                targetSelect.value = `prompt:${firstPrompt.id}`;
            }

            // Load config for the first prompt
            await loadPromptConfig(firstPrompt);
        } else {
            // Fallback to old behavior if no prompts
            await loadConfig();
        }
    } catch (error) {
        console.error('Failed to load execution targets:', error);
        // Fallback to old behavior
        await loadConfig();
    }
}

/**
 * NEW ARCHITECTURE: Update the execution target selector dropdown
 */
function updateExecutionTargetSelector(targets) {
    const targetSelect = document.getElementById('single-target-select');
    if (!targetSelect) {
        console.log('Target selector not found, skipping update');
        return;
    }

    let options = '';

    // Add prompts
    if (targets.prompts && targets.prompts.length > 0) {
        options += '<optgroup label="プロンプト / Prompts">';
        targets.prompts.forEach(prompt => {
            options += `<option value="prompt:${prompt.id}">${prompt.name}</option>`;
        });
        options += '</optgroup>';
    }

    // Add workflows
    if (targets.workflows && targets.workflows.length > 0) {
        options += '<optgroup label="ワークフロー / Workflows">';
        targets.workflows.forEach(workflow => {
            options += `<option value="workflow:${workflow.id}">${workflow.name} (${workflow.step_count} steps)</option>`;
        });
        options += '</optgroup>';
    }

    targetSelect.innerHTML = options;
    targetSelect.style.display = options ? 'block' : 'none';
}

/**
 * NEW ARCHITECTURE: Handle execution target selection (prompt or workflow within a project)
 */
async function onExecutionTargetChange(e) {
    const value = e.target.value;
    const [type, id] = value.split(':');

    if (type === 'workflow') {
        currentSelectionType = 'workflow';
        currentWorkflowId = parseInt(id);
        currentPromptId = null;
        await loadWorkflowConfig(currentWorkflowId);
    } else if (type === 'prompt') {
        currentSelectionType = 'prompt';
        currentPromptId = parseInt(id);
        currentWorkflowId = null;

        // Find the prompt in currentExecutionTargets
        const prompt = currentExecutionTargets?.prompts?.find(p => p.id === currentPromptId);
        if (prompt) {
            await loadPromptConfig(prompt);
        }
    }
}

/**
 * NEW ARCHITECTURE: Load configuration for a specific prompt
 */
async function loadPromptConfig(prompt) {
    try {
        // Preserve existing recent_jobs when updating config
        const existingJobs = currentConfig?.recent_jobs || [];

        // Update current config from prompt data
        currentConfig = {
            prompt_template: prompt.prompt_template,
            parser_config: prompt.parser_config,
            parameters: prompt.parameters,
            recent_jobs: existingJobs  // Preserve history
        };

        currentParameters = prompt.parameters || [];

        // Update prompt template display
        const templateDisplay = document.getElementById('prompt-template');
        if (templateDisplay) {
            templateDisplay.textContent = prompt.prompt_template || '';
        }

        // Render parameter inputs
        renderParameterInputs();

        showStatus(`プロンプト "${prompt.name}" を読み込みました`, 'success');
    } catch (error) {
        showStatus(`プロンプト読み込みエラー: ${error.message}`, 'error');
    }
}

/**
 * NEW ARCHITECTURE: Show add prompt modal
 */
async function showAddPromptModal() {
    if (!currentProjectId) {
        alert('プロジェクトを選択してください / Please select a project');
        return;
    }

    const modalContent = `
        <div class="modal-header">
            新規プロンプト作成 / Create New Prompt
        </div>
        <div class="modal-body">
            <div class="form-group">
                <label>プロンプト名 / Prompt Name:</label>
                <input type="text" id="new-prompt-name" style="width: 100%; padding: 0.5rem; box-sizing: border-box;" placeholder="例: 要約プロンプト">
            </div>
            <div class="form-group">
                <label>説明 / Description:</label>
                <input type="text" id="new-prompt-description" style="width: 100%; padding: 0.5rem; box-sizing: border-box;" placeholder="例: テキストを要約するプロンプト">
            </div>
            <div class="form-group">
                <label>プロンプトテンプレート / Prompt Template:</label>
                <textarea id="new-prompt-template" rows="10" style="font-family: 'Courier New', monospace; width: 100%; box-sizing: border-box;">以下の指示に従って回答してください。

{{INPUT:TEXT10}}

回答:</textarea>
            </div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
            <button class="btn btn-primary" onclick="createNewPrompt()">作成 / Create</button>
        </div>
    `;
    showModal(modalContent);
}

/**
 * NEW ARCHITECTURE: Create new prompt
 */
async function createNewPrompt() {
    const name = document.getElementById('new-prompt-name').value.trim();
    const description = document.getElementById('new-prompt-description').value.trim();
    const template = document.getElementById('new-prompt-template').value;

    if (!name) {
        alert('プロンプト名を入力してください / Please enter a prompt name');
        return;
    }

    try {
        const response = await fetch(`/api/projects/${currentProjectId}/prompts`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                name: name,
                description: description,
                prompt_template: template
            })
        });

        if (!response.ok) throw new Error('Failed to create prompt');

        const newPrompt = await response.json();
        closeModal();

        // Reload execution targets and select the new prompt
        await loadExecutionTargets(currentProjectId);

        // Select the newly created prompt
        const targetSelect = document.getElementById('single-target-select');
        if (targetSelect) {
            targetSelect.value = `prompt:${newPrompt.id}`;
            currentPromptId = newPrompt.id;
            currentSelectionType = 'prompt';
            await loadPromptConfig(newPrompt);
        }

        showStatus(`プロンプト「${name}」を作成しました / Created prompt "${name}"`, 'success');
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * NEW ARCHITECTURE: Delete current prompt
 */
async function deleteCurrentPrompt() {
    if (!currentPromptId) {
        alert('削除するプロンプトを選択してください / Please select a prompt to delete');
        return;
    }

    // Find prompt name from currentExecutionTargets
    const prompt = currentExecutionTargets?.prompts?.find(p => p.id === currentPromptId);
    const promptName = prompt ? prompt.name : `ID: ${currentPromptId}`;

    if (!confirm(`プロンプト「${promptName}」を削除しますか？\nこの操作は取り消せません。\n\nDelete prompt "${promptName}"?\nThis action cannot be undone.`)) {
        return;
    }

    try {
        const response = await fetch(`/api/prompts/${currentPromptId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to delete prompt');
        }

        // Close modal if open
        closeModal();

        showStatus(`プロンプト「${promptName}」を削除しました / Deleted prompt "${promptName}"`, 'success');

        // Reload execution targets (will auto-select first prompt)
        currentPromptId = null;
        await loadExecutionTargets(currentProjectId);

    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Show edit prompt modal
 * NEW ARCHITECTURE: Uses PromptRevision instead of ProjectRevision
 * Specification: docs/req.txt section 4.4.3 (Revision Management)
 */
async function showEditPromptModal() {
    // NEW ARCHITECTURE: Use currentPromptId if available
    if (currentSelectionType === 'prompt' && currentPromptId) {
        await showEditPromptModalNewArch();
        return;
    }

    // Fallback to old behavior for backward compatibility
    try {
        const [projectResponse, revisionsResponse] = await Promise.all([
            fetch(`/api/projects/${currentProjectId}`),
            fetch(`/api/projects/${currentProjectId}/revisions`)
        ]);

        if (!projectResponse.ok) throw new Error('Failed to load project');
        const project = await projectResponse.json();
        const revisions = revisionsResponse.ok ? await revisionsResponse.json() : [];

        const revisionOptions = revisions.map(rev => {
            const date = formatJST(rev.created_at);
            const isCurrent = rev.revision === project.revision_count;
            return `<option value="${rev.revision}" ${isCurrent ? 'selected' : ''}>
                Rev.${rev.revision} (${date})${isCurrent ? ' - 現在' : ''}
            </option>`;
        }).join('');

        const modalContent = `
            <div class="modal-header">
                プロンプトテンプレート編集 / Edit Prompt Template
                <button onclick="showPromptTemplateHelp()" style="background: none; border: none; cursor: pointer; font-size: 1.2rem; margin-left: 10px;" title="ヘルプを表示 / Show Help">❓</button>
            </div>
            <div class="modal-body">
                <div class="form-group">
                    <label>プロジェクト / Project: ${project.name}</label>
                </div>
                <div class="form-group" style="display: flex; align-items: center; gap: 10px;">
                    <label style="margin: 0;">リビジョン / Revision:</label>
                    <select id="revision-selector" onchange="loadRevisionContent(this.value, 'prompt')" style="flex: 1;">
                        ${revisionOptions}
                    </select>
                    <button class="btn btn-secondary" onclick="restoreRevision('prompt')" style="background-color: #e67e22;" title="選択したリビジョンを復元 / Restore selected revision">
                        🔄 復元 / Restore
                    </button>
                </div>
                <div class="form-group">
                    <label>プロンプトテンプレート / Prompt Template:</label>
                    <textarea id="edit-prompt-template" rows="15" style="font-family: 'Courier New', monospace; width: 100%; box-sizing: border-box;">${project.prompt_template}</textarea>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
                <button class="btn btn-primary" onclick="savePromptRevision()">保存 / Save</button>
            </div>
        `;
        showModal(modalContent);
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * NEW ARCHITECTURE: Unified Prompt Management Modal
 * Features:
 * - Prompt selector dropdown to switch between prompts
 * - Tab interface for Prompt Template / Parser Config
 * - Create/Delete buttons
 * - Revision selector with restore
 */
let currentModalTab = 'prompt';  // 'prompt' or 'parser'
let currentModalPromptId = null;
let currentModalPromptData = null;
let currentModalRevisions = [];

async function showPromptManagementModal(initialTab = 'prompt') {
    if (!currentProjectId) {
        alert('プロジェクトを選択してください / Please select a project');
        return;
    }

    currentModalTab = initialTab;
    currentModalPromptId = currentPromptId;

    try {
        // Load all prompts for this project
        const targetsResponse = await fetch(`/api/projects/${currentProjectId}/execution-targets`);
        if (!targetsResponse.ok) throw new Error('Failed to load prompts');
        const targets = await targetsResponse.json();
        const prompts = targets.prompts || [];

        if (prompts.length === 0) {
            alert('プロンプトがありません / No prompts available');
            return;
        }

        // If no prompt selected, use the first one
        if (!currentModalPromptId) {
            currentModalPromptId = prompts[0].id;
        }

        await renderPromptManagementModal(prompts);
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

async function renderPromptManagementModal(prompts) {
    // Load current prompt data and revisions
    const [promptResponse, revisionsResponse] = await Promise.all([
        fetch(`/api/prompts/${currentModalPromptId}`),
        fetch(`/api/prompts/${currentModalPromptId}/revisions`)
    ]);

    if (!promptResponse.ok) throw new Error('Failed to load prompt');
    currentModalPromptData = await promptResponse.json();
    currentModalRevisions = revisionsResponse.ok ? await revisionsResponse.json() : [];

    // Build prompt selector options
    const promptOptions = prompts.map(p =>
        `<option value="${p.id}" ${p.id === currentModalPromptId ? 'selected' : ''}>${p.name}</option>`
    ).join('');

    // Build revision selector options
    const revisionOptions = currentModalRevisions.map(rev => {
        const date = formatJST(rev.created_at);
        const isCurrent = rev.revision === currentModalPromptData.revision_count;
        return `<option value="${rev.revision}" ${isCurrent ? 'selected' : ''}>
            Rev.${rev.revision} (${date})${isCurrent ? ' - 現在' : ''}
        </option>`;
    }).join('');

    // Parse parser config
    let parserConfig = {type: 'none'};
    try {
        if (currentModalPromptData.parser_config) {
            parserConfig = JSON.parse(currentModalPromptData.parser_config);
        }
    } catch (e) { /* ignore */ }

    // Tab content based on current tab
    const promptTabActive = currentModalTab === 'prompt';
    const parserTabActive = currentModalTab === 'parser';

    // Textarea sizing: consistent height across tabs to prevent size change on tab switch
    // Parser tab has extra selector (~70px), so prompt textarea is larger to match total height
    const promptContent = `
        <div class="form-group" style="margin: 0;">
            <label style="display: block; margin-bottom: 5px;">プロンプトテンプレート / Prompt Template:</label>
            <textarea id="edit-prompt-template" style="font-family: 'Courier New', monospace; width: 100%; box-sizing: border-box; height: 550px; max-height: 2000px; resize: vertical;">${currentModalPromptData.prompt_template || ''}</textarea>
        </div>
    `;

    const parserContent = `
        <div class="form-group" style="margin-bottom: 10px;">
            <label>パーサータイプ / Parser Type:</label>
            <select id="edit-parser-type" style="width: 100%; padding: 0.5rem;">
                <option value="none" ${parserConfig.type === 'none' ? 'selected' : ''}>なし / None</option>
                <option value="json_path" ${parserConfig.type === 'json_path' ? 'selected' : ''}>JSON Path</option>
                <option value="regex" ${parserConfig.type === 'regex' ? 'selected' : ''}>正規表現 / Regex</option>
                <option value="csv" ${parserConfig.type === 'csv' ? 'selected' : ''}>CSV</option>
            </select>
        </div>
        <div class="form-group" style="margin: 0;">
            <label style="display: block; margin-bottom: 5px;">パーサー設定 (JSON) / Parser Config:</label>
            <textarea id="edit-parser-config" style="font-family: 'Courier New', monospace; width: 100%; box-sizing: border-box; height: 480px; max-height: 2000px; resize: vertical;">${JSON.stringify(parserConfig, null, 2)}</textarea>
        </div>
    `;

    const modalContent = `
        <div class="modal-header" style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
            <span style="font-weight: bold; font-size: 1.1rem;">
                プロンプト管理 / Prompt Management
                <button onclick="showUnifiedHelp()" style="background: none; border: none; cursor: pointer; font-size: 1rem; margin-left: 5px;" title="ヘルプ / Help">❓</button>
            </span>
            <button class="btn btn-success" onclick="showAddPromptModalFromManagement()" style="font-size: 0.85rem;" title="新規プロンプト作成 / Create new prompt">
                ＋ 新規作成 / New
            </button>
        </div>
        <div class="modal-body" style="overflow-y: auto;">
            <!-- Prompt Selector -->
            <div class="form-group" style="display: flex; align-items: center; gap: 10px; margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid #ddd;">
                <label style="margin: 0; white-space: nowrap;">プロンプト / Prompt:</label>
                <select id="modal-prompt-selector" onchange="onModalPromptChange(this.value)" style="flex: 1; padding: 0.4rem;">
                    ${promptOptions}
                </select>
                <button class="btn btn-danger" onclick="deletePromptFromModal()" style="font-size: 0.85rem;" title="削除 / Delete">
                    🗑
                </button>
            </div>

            <!-- Tab Navigation -->
            <div style="display: flex; gap: 0; margin-bottom: 10px; border-bottom: 2px solid #007bff;">
                <button id="tab-btn-prompt" onclick="switchModalTab('prompt')"
                    style="padding: 8px 20px; border: none; background: ${promptTabActive ? '#007bff' : '#e9ecef'}; color: ${promptTabActive ? 'white' : '#333'}; cursor: pointer; border-radius: 5px 5px 0 0; font-weight: ${promptTabActive ? 'bold' : 'normal'};">
                    プロンプト / Prompt
                </button>
                <button id="tab-btn-parser" onclick="switchModalTab('parser')"
                    style="padding: 8px 20px; border: none; background: ${parserTabActive ? '#007bff' : '#e9ecef'}; color: ${parserTabActive ? 'white' : '#333'}; cursor: pointer; border-radius: 5px 5px 0 0; font-weight: ${parserTabActive ? 'bold' : 'normal'};">
                    パーサー / Parser
                </button>
            </div>

            <!-- Revision Selector -->
            <div class="form-group" style="display: flex; align-items: center; gap: 10px; margin-bottom: 10px;">
                <label style="margin: 0; white-space: nowrap;">リビジョン / Rev:</label>
                <select id="revision-selector" onchange="loadModalRevisionContent(this.value)" style="flex: 1; padding: 0.4rem;">
                    ${revisionOptions}
                </select>
                <button class="btn btn-secondary" onclick="restoreModalRevision()" style="background-color: #e67e22; font-size: 0.85rem;" title="復元 / Restore">
                    🔄 復元
                </button>
            </div>

            <!-- Tab Content - no height restriction, textarea can grow freely -->
            <div id="modal-tab-content">
                ${promptTabActive ? promptContent : parserContent}
            </div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
            <button class="btn btn-primary" onclick="saveModalContent()">保存 / Save</button>
        </div>
    `;
    showModal(modalContent);
}

async function onModalPromptChange(promptId) {
    currentModalPromptId = parseInt(promptId);
    // Reload modal with new prompt
    const targetsResponse = await fetch(`/api/projects/${currentProjectId}/execution-targets`);
    if (targetsResponse.ok) {
        const targets = await targetsResponse.json();
        await renderPromptManagementModal(targets.prompts || []);
    }
}

function switchModalTab(tab) {
    currentModalTab = tab;

    // Update tab button styles
    const promptBtn = document.getElementById('tab-btn-prompt');
    const parserBtn = document.getElementById('tab-btn-parser');

    if (tab === 'prompt') {
        promptBtn.style.background = '#007bff';
        promptBtn.style.color = 'white';
        promptBtn.style.fontWeight = 'bold';
        parserBtn.style.background = '#e9ecef';
        parserBtn.style.color = '#333';
        parserBtn.style.fontWeight = 'normal';
    } else {
        parserBtn.style.background = '#007bff';
        parserBtn.style.color = 'white';
        parserBtn.style.fontWeight = 'bold';
        promptBtn.style.background = '#e9ecef';
        promptBtn.style.color = '#333';
        promptBtn.style.fontWeight = 'normal';
    }

    // Update tab content - consistent height across tabs
    const contentDiv = document.getElementById('modal-tab-content');
    if (tab === 'prompt') {
        contentDiv.innerHTML = `
            <div class="form-group" style="margin: 0;">
                <label style="display: block; margin-bottom: 5px;">プロンプトテンプレート / Prompt Template:</label>
                <textarea id="edit-prompt-template" style="font-family: 'Courier New', monospace; width: 100%; box-sizing: border-box; height: 550px; max-height: 2000px; resize: vertical;">${currentModalPromptData.prompt_template || ''}</textarea>
            </div>
        `;
    } else {
        let parserConfig = {type: 'none'};
        try {
            if (currentModalPromptData.parser_config) {
                parserConfig = JSON.parse(currentModalPromptData.parser_config);
            }
        } catch (e) { /* ignore */ }

        contentDiv.innerHTML = `
            <div class="form-group" style="margin-bottom: 10px;">
                <label>パーサータイプ / Parser Type:</label>
                <select id="edit-parser-type" style="width: 100%; padding: 0.5rem;">
                    <option value="none" ${parserConfig.type === 'none' ? 'selected' : ''}>なし / None</option>
                    <option value="json_path" ${parserConfig.type === 'json_path' ? 'selected' : ''}>JSON Path</option>
                    <option value="regex" ${parserConfig.type === 'regex' ? 'selected' : ''}>正規表現 / Regex</option>
                    <option value="csv" ${parserConfig.type === 'csv' ? 'selected' : ''}>CSV</option>
                </select>
            </div>
            <div class="form-group" style="margin: 0;">
                <label style="display: block; margin-bottom: 5px;">パーサー設定 (JSON) / Parser Config:</label>
                <textarea id="edit-parser-config" style="font-family: 'Courier New', monospace; width: 100%; box-sizing: border-box; height: 480px; max-height: 2000px; resize: vertical;">${JSON.stringify(parserConfig, null, 2)}</textarea>
            </div>
        `;
    }
}

async function loadModalRevisionContent(revisionNumber) {
    const revision = currentModalRevisions.find(r => r.revision === parseInt(revisionNumber));
    if (!revision) return;

    if (currentModalTab === 'prompt') {
        document.getElementById('edit-prompt-template').value = revision.prompt_template || '';
    } else {
        let parserConfig = {type: 'none'};
        try {
            if (revision.parser_config) {
                parserConfig = JSON.parse(revision.parser_config);
            }
        } catch (e) { /* ignore */ }
        document.getElementById('edit-parser-type').value = parserConfig.type || 'none';
        document.getElementById('edit-parser-config').value = JSON.stringify(parserConfig, null, 2);
    }
}

async function restoreModalRevision() {
    const selector = document.getElementById('revision-selector');
    if (!selector) return;

    const revisionNumber = parseInt(selector.value);
    const selectedOption = selector.options[selector.selectedIndex];
    const isCurrent = selectedOption.text.includes('現在');

    if (isCurrent) {
        alert('現在のリビジョンは復元できません\nCannot restore current revision');
        return;
    }

    if (!confirm(`リビジョン ${revisionNumber} を復元しますか？\nRestore revision ${revisionNumber}?`)) {
        return;
    }

    try {
        const response = await fetch(`/api/prompts/${currentModalPromptId}/revisions/${revisionNumber}/restore`, {
            method: 'POST'
        });

        if (!response.ok) throw new Error('Failed to restore revision');

        const result = await response.json();
        showStatus(`リビジョン ${revisionNumber} を復元しました (Rev.${result.revision})`, 'success');

        // Reload modal
        const targetsResponse = await fetch(`/api/projects/${currentProjectId}/execution-targets`);
        if (targetsResponse.ok) {
            const targets = await targetsResponse.json();
            await renderPromptManagementModal(targets.prompts || []);
        }
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

async function saveModalContent() {
    try {
        let body = {};

        if (currentModalTab === 'prompt') {
            const template = document.getElementById('edit-prompt-template').value;
            if (!template.trim()) {
                alert('プロンプトテンプレートを入力してください / Please enter a prompt template');
                return;
            }
            body.prompt_template = template;
        } else {
            const parserType = document.getElementById('edit-parser-type').value;
            const parserConfigText = document.getElementById('edit-parser-config').value;

            try {
                const parsed = JSON.parse(parserConfigText);
                parsed.type = parserType;
                body.parser_config = JSON.stringify(parsed);
            } catch (e) {
                body.parser_config = JSON.stringify({type: parserType});
            }
        }

        const response = await fetch(`/api/prompts/${currentModalPromptId}/revisions/latest`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body)
        });

        if (!response.ok) throw new Error('Failed to save');

        const result = await response.json();

        if (result.is_new) {
            showStatus(`保存しました (Rev.${result.revision}) / Saved (Rev.${result.revision})`, 'success');
        } else {
            showStatus('変更なし / No changes', 'info');
        }

        closeModal();

        // Update main UI if the saved prompt is currently selected
        if (currentModalPromptId === currentPromptId) {
            await loadExecutionTargets(currentProjectId);
        }
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

async function showAddPromptModalFromManagement() {
    // Show create prompt modal, then return to management modal
    const modalContent = `
        <div class="modal-header">
            新規プロンプト作成 / Create New Prompt
        </div>
        <div class="modal-body">
            <div class="form-group">
                <label>プロンプト名 / Prompt Name:</label>
                <input type="text" id="new-prompt-name" style="width: 100%; padding: 0.5rem; box-sizing: border-box;" placeholder="例: 要約プロンプト">
            </div>
            <div class="form-group">
                <label>説明 / Description:</label>
                <input type="text" id="new-prompt-description" style="width: 100%; padding: 0.5rem; box-sizing: border-box;" placeholder="例: テキストを要約するプロンプト">
            </div>
            <div class="form-group">
                <label>プロンプトテンプレート / Prompt Template:</label>
                <textarea id="new-prompt-template" rows="8" style="font-family: 'Courier New', monospace; width: 100%; box-sizing: border-box;">以下の指示に従って回答してください。

{{INPUT:TEXT10}}

回答:</textarea>
            </div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="showPromptManagementModal('${currentModalTab}')">戻る / Back</button>
            <button class="btn btn-primary" onclick="createPromptAndReturn()">作成 / Create</button>
        </div>
    `;
    showModal(modalContent);
}

async function createPromptAndReturn() {
    const name = document.getElementById('new-prompt-name').value.trim();
    const description = document.getElementById('new-prompt-description').value.trim();
    const template = document.getElementById('new-prompt-template').value;

    if (!name) {
        alert('プロンプト名を入力してください / Please enter a prompt name');
        return;
    }

    try {
        const response = await fetch(`/api/projects/${currentProjectId}/prompts`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                name: name,
                description: description,
                prompt_template: template
            })
        });

        if (!response.ok) throw new Error('Failed to create prompt');

        const newPrompt = await response.json();
        showStatus(`プロンプト「${name}」を作成しました / Created prompt "${name}"`, 'success');

        // Select the new prompt and return to management modal
        currentModalPromptId = newPrompt.id;
        currentPromptId = newPrompt.id;
        await showPromptManagementModal(currentModalTab);

        // Also update main UI
        await loadExecutionTargets(currentProjectId);
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

async function deletePromptFromModal() {
    const prompt = currentModalPromptData;
    if (!prompt) return;

    if (!confirm(`プロンプト「${prompt.name}」を削除しますか？\nDelete prompt "${prompt.name}"?`)) {
        return;
    }

    try {
        const response = await fetch(`/api/prompts/${currentModalPromptId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to delete prompt');
        }

        showStatus(`プロンプトを削除しました / Prompt deleted`, 'success');

        // Reload management modal with first available prompt
        currentModalPromptId = null;
        currentPromptId = null;

        const targetsResponse = await fetch(`/api/projects/${currentProjectId}/execution-targets`);
        if (targetsResponse.ok) {
            const targets = await targetsResponse.json();
            if (targets.prompts && targets.prompts.length > 0) {
                currentModalPromptId = targets.prompts[0].id;
                await renderPromptManagementModal(targets.prompts);
            } else {
                closeModal();
            }
        }

        // Update main UI
        await loadExecutionTargets(currentProjectId);
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

// Keep old function as alias for backward compatibility
async function showEditPromptModalNewArch() {
    await showPromptManagementModal('prompt');
}

/**
 * Save (update) current prompt revision
 * Smart save: Creates new revision only if content changed
 * Specification: docs/req.txt section 4.4.3 - 保存ボタン
 */
async function savePromptRevision() {
    const newTemplate = document.getElementById('edit-prompt-template').value;
    if (!newTemplate.trim()) {
        alert('プロンプトテンプレートを入力してください / Please enter a prompt template');
        return;
    }

    try {
        const response = await fetch(`/api/projects/${currentProjectId}/revisions/latest`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                prompt_template: newTemplate
            })
        });

        if (!response.ok) throw new Error('Failed to save revision');

        const result = await response.json();
        closeModal();
        await loadConfig();

        if (result.is_new) {
            alert(`新しいリビジョン ${result.revision} を作成しました / New revision ${result.revision} created`);
        } else {
            alert('変更がありませんでした / No changes detected');
        }
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Load revision content into the editor
 * @param {number} revisionNumber - The revision number to load
 * @param {string} type - 'prompt' or 'parser'
 */
async function loadRevisionContent(revisionNumber, type) {
    try {
        const response = await fetch(`/api/projects/${currentProjectId}/revisions`);
        if (!response.ok) throw new Error('Failed to load revisions');

        const revisions = await response.json();
        const revision = revisions.find(r => r.revision === parseInt(revisionNumber));

        if (!revision) {
            alert('リビジョンが見つかりません / Revision not found');
            return;
        }

        if (type === 'prompt') {
            document.getElementById('edit-prompt-template').value = revision.prompt_template;
        } else if (type === 'parser') {
            const parserConfig = revision.parser_config ? JSON.parse(revision.parser_config) : {type: 'none'};
            document.getElementById('edit-parser-type').value = parserConfig.type || 'none';
            document.getElementById('edit-parser-config').value = JSON.stringify(parserConfig, null, 2);
        }
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Restore a past revision (creates new revision with old content)
 * @param {string} type - 'prompt' or 'parser' (for context, restore applies to both)
 */
async function restoreRevision(type) {
    const selector = document.getElementById('revision-selector');
    if (!selector) {
        alert('リビジョンセレクタが見つかりません / Revision selector not found');
        return;
    }

    const revisionNumber = parseInt(selector.value);
    const selectedOption = selector.options[selector.selectedIndex];
    const isCurrent = selectedOption.text.includes('現在');

    if (isCurrent) {
        alert('現在のリビジョンは復元できません（既に最新です）\nCannot restore current revision (already latest)');
        return;
    }

    if (!confirm(`リビジョン ${revisionNumber} を復元しますか？\n新しいリビジョンとして作成されます。\n\nRestore revision ${revisionNumber}?\nThis will create a new revision.`)) {
        return;
    }

    try {
        const response = await fetch(`/api/projects/${currentProjectId}/revisions/${revisionNumber}/restore`, {
            method: 'POST'
        });

        if (!response.ok) throw new Error('Failed to restore revision');

        const result = await response.json();
        closeModal();
        await loadConfig();
        alert(`リビジョン ${revisionNumber} を復元しました（新リビジョン: ${result.revision}）\nRestored revision ${revisionNumber} (new revision: ${result.revision})`);
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * NEW ARCHITECTURE: Save prompt revision using PromptRevision API
 */
async function savePromptRevisionNewArch() {
    const newTemplate = document.getElementById('edit-prompt-template').value;
    if (!newTemplate.trim()) {
        alert('プロンプトテンプレートを入力してください / Please enter a prompt template');
        return;
    }

    try {
        const response = await fetch(`/api/prompts/${currentPromptId}/revisions/latest`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                prompt_template: newTemplate
            })
        });

        if (!response.ok) throw new Error('Failed to save revision');

        const result = await response.json();
        closeModal();

        // Reload execution targets to refresh the prompt data
        await loadExecutionTargets(currentProjectId);

        // Re-select the current prompt
        const targetSelect = document.getElementById('single-target-select');
        if (targetSelect) {
            targetSelect.value = `prompt:${currentPromptId}`;
        }

        // Reload the prompt config
        const prompt = currentExecutionTargets?.prompts?.find(p => p.id === currentPromptId);
        if (prompt) {
            await loadPromptConfig(prompt);
        }

        if (result.is_new) {
            showStatus(`新しいリビジョン ${result.revision} を作成しました / New revision ${result.revision} created`, 'success');
        } else {
            showStatus('変更がありませんでした / No changes detected', 'info');
        }
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * NEW ARCHITECTURE: Load prompt revision content into the editor
 */
async function loadPromptRevisionContent(revisionNumber, type) {
    try {
        const response = await fetch(`/api/prompts/${currentPromptId}/revisions`);
        if (!response.ok) throw new Error('Failed to load revisions');

        const revisions = await response.json();
        const revision = revisions.find(r => r.revision === parseInt(revisionNumber));

        if (!revision) {
            alert('リビジョンが見つかりません / Revision not found');
            return;
        }

        if (type === 'prompt') {
            document.getElementById('edit-prompt-template').value = revision.prompt_template;
        } else if (type === 'parser') {
            const parserConfig = revision.parser_config ? JSON.parse(revision.parser_config) : {type: 'none'};
            document.getElementById('edit-parser-type').value = parserConfig.type || 'none';
            document.getElementById('edit-parser-config').value = JSON.stringify(parserConfig, null, 2);
        }
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * NEW ARCHITECTURE: Restore a past prompt revision
 */
async function restorePromptRevision(type) {
    const selector = document.getElementById('revision-selector');
    if (!selector) {
        alert('リビジョンセレクタが見つかりません / Revision selector not found');
        return;
    }

    const revisionNumber = parseInt(selector.value);
    const selectedOption = selector.options[selector.selectedIndex];
    const isCurrent = selectedOption.text.includes('現在');

    if (isCurrent) {
        alert('現在のリビジョンは復元できません（既に最新です）\nCannot restore current revision (already latest)');
        return;
    }

    if (!confirm(`リビジョン ${revisionNumber} を復元しますか？\n新しいリビジョンとして作成されます。\n\nRestore revision ${revisionNumber}?\nThis will create a new revision.`)) {
        return;
    }

    try {
        const response = await fetch(`/api/prompts/${currentPromptId}/revisions/${revisionNumber}/restore`, {
            method: 'POST'
        });

        if (!response.ok) throw new Error('Failed to restore revision');

        const result = await response.json();
        closeModal();

        // Reload execution targets
        await loadExecutionTargets(currentProjectId);

        // Re-select the current prompt
        const targetSelect = document.getElementById('single-target-select');
        if (targetSelect) {
            targetSelect.value = `prompt:${currentPromptId}`;
        }

        // Reload the prompt config
        const prompt = currentExecutionTargets?.prompts?.find(p => p.id === currentPromptId);
        if (prompt) {
            await loadPromptConfig(prompt);
        }

        showStatus(`リビジョン ${revisionNumber} を復元しました（新リビジョン: ${result.revision}）`, 'success');
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Show edit parser modal
 * NEW ARCHITECTURE: Uses PromptRevision if currentPromptId is set
 * Specification: docs/req.txt section 6.2 (Response Parser)
 */
async function showEditParserModal() {
    // NEW ARCHITECTURE: Use currentPromptId if available
    if (currentSelectionType === 'prompt' && currentPromptId) {
        await showEditParserModalNewArch();
        return;
    }

    // Fallback to old behavior
    try {
        const [projectResponse, revisionsResponse] = await Promise.all([
            fetch(`/api/projects/${currentProjectId}`),
            fetch(`/api/projects/${currentProjectId}/revisions`)
        ]);

        if (!projectResponse.ok) throw new Error('Failed to load project');
        const project = await projectResponse.json();
        const revisions = revisionsResponse.ok ? await revisionsResponse.json() : [];

        const parserConfig = project.parser_config || {type: 'none'};
        const parserJson = JSON.stringify(parserConfig, null, 2);

        const revisionOptions = revisions.map(rev => {
            const date = formatJST(rev.created_at);
            const isCurrent = rev.revision === project.revision_count;
            return `<option value="${rev.revision}" ${isCurrent ? 'selected' : ''}>
                Rev.${rev.revision} (${date})${isCurrent ? ' - 現在' : ''}
            </option>`;
        }).join('');

        const modalContent = `
            <div class="modal-header">
                パーサー設定編集 / Edit Parser Configuration
                <button onclick="showParserHelp()" style="background: none; border: none; cursor: pointer; font-size: 1.2rem; margin-left: 10px;" title="ヘルプを表示 / Show Help">❓</button>
            </div>
            <div class="modal-body">
                <div class="form-group">
                    <label>プロジェクト / Project: ${project.name}</label>
                </div>
                <div class="form-group" style="display: flex; align-items: center; gap: 10px;">
                    <label style="margin: 0;">リビジョン / Revision:</label>
                    <select id="revision-selector" onchange="loadRevisionContent(this.value, 'parser')" style="flex: 1;">
                        ${revisionOptions}
                    </select>
                    <button class="btn btn-secondary" onclick="restoreRevision('parser')" style="background-color: #e67e22;" title="選択したリビジョンを復元 / Restore selected revision">
                        🔄 復元 / Restore
                    </button>
                </div>
                <div class="form-group">
                    <label>パーサータイプ / Parser Type:</label>
                    <select id="edit-parser-type">
                        <option value="none" ${parserConfig.type === 'none' ? 'selected' : ''}>なし / None</option>
                        <option value="json_path" ${parserConfig.type === 'json_path' ? 'selected' : ''}>JSON Path</option>
                        <option value="regex" ${parserConfig.type === 'regex' ? 'selected' : ''}>正規表現 / Regex</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>パーサー設定 (JSON) / Parser Configuration (JSON):</label>
                    <textarea id="edit-parser-config" rows="12" style="font-family: 'Courier New', monospace;">${parserJson}</textarea>
                    <small style="color: #7f8c8d;">
                        JSON Path例: {"type": "json_path", "paths": {"answer": "$.answer"}}<br>
                        正規表現例: {"type": "regex", "patterns": {"answer": "Answer: (.+)"}}
                    </small>
                </div>
            </div>
            <div class="modal-footer" style="display: flex; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem;">
                <button class="btn" onclick="showJsonToCsvConverter()" style="background-color: #9b59b6;">📊 結果からCSVに変換 / Convert JSON to CSV</button>
                <div style="display: flex; gap: 0.5rem;">
                    <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
                    <button class="btn btn-primary" onclick="saveParserRevision()">保存 / Save</button>
                </div>
            </div>
        `;
        showModal(modalContent);
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * NEW ARCHITECTURE: Show edit parser modal using PromptRevision
 * Now redirects to unified prompt management modal with parser tab
 */
async function showEditParserModalNewArch() {
    await showPromptManagementModal('parser');
}

/**
 * Save (update) current parser revision
 * Smart save: Creates new revision only if content changed
 * Specification: docs/req.txt section 4.4.3 - 保存ボタン
 */
async function saveParserRevision() {
    const parserType = document.getElementById('edit-parser-type').value;
    const parserConfigText = document.getElementById('edit-parser-config').value;

    let parserConfig;
    try {
        parserConfig = JSON.parse(parserConfigText);
        parserConfig.type = parserType; // Ensure type matches selection
    } catch (error) {
        alert('パーサー設定のJSON形式が不正です / Invalid JSON format for parser configuration');
        return;
    }

    try {
        const response = await fetch(`/api/projects/${currentProjectId}/revisions/latest`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                parser_config: JSON.stringify(parserConfig)
            })
        });

        if (!response.ok) throw new Error('Failed to save revision');

        const result = await response.json();
        closeModal();
        await loadConfig();

        if (result.is_new) {
            alert(`新しいリビジョン ${result.revision} を作成しました / New revision ${result.revision} created`);
        } else {
            alert('変更がありませんでした / No changes detected');
        }
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * NEW ARCHITECTURE: Save parser revision using PromptRevision API
 */
async function saveParserRevisionNewArch() {
    const parserType = document.getElementById('edit-parser-type').value;
    const parserConfigText = document.getElementById('edit-parser-config').value;

    let parserConfig;
    try {
        parserConfig = JSON.parse(parserConfigText);
        parserConfig.type = parserType; // Ensure type matches selection
    } catch (error) {
        alert('パーサー設定のJSON形式が不正です / Invalid JSON format for parser configuration');
        return;
    }

    try {
        const response = await fetch(`/api/prompts/${currentPromptId}/revisions/latest`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                parser_config: JSON.stringify(parserConfig)
            })
        });

        if (!response.ok) throw new Error('Failed to save revision');

        const result = await response.json();
        closeModal();

        // Reload execution targets
        await loadExecutionTargets(currentProjectId);

        // Re-select the current prompt
        const targetSelect = document.getElementById('single-target-select');
        if (targetSelect) {
            targetSelect.value = `prompt:${currentPromptId}`;
        }

        // Reload the prompt config
        const prompt = currentExecutionTargets?.prompts?.find(p => p.id === currentPromptId);
        if (prompt) {
            await loadPromptConfig(prompt);
        }

        if (result.is_new) {
            showStatus(`新しいリビジョン ${result.revision} を作成しました / New revision ${result.revision} created`, 'success');
        } else {
            showStatus('変更がありませんでした / No changes detected', 'info');
        }
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

// ========== BATCH EXECUTION EDIT MODALS ==========

/**
 * Show batch edit prompt modal
 * Now uses the unified prompt management modal
 */
async function showBatchEditPromptModal() {
    const selectValue = document.getElementById('batch-project-select').value;
    if (!selectValue) {
        alert('プロジェクトを選択してください / Please select a project');
        return;
    }

    const parsed = parseSelectValue(selectValue);
    if (!parsed || parsed.type !== 'project' || !parsed.id) {
        alert('プロジェクトを選択してください / Please select a project');
        return;
    }

    // Set currentProjectId for the unified modal
    currentProjectId = parsed.id;

    // Use the unified prompt management modal
    await showPromptManagementModal('prompt');
}

/**
 * Save batch prompt revision
 * Smart save: Creates new revision only if content changed
 */
async function saveBatchPromptRevision(projectId) {
    const newTemplate = document.getElementById('edit-prompt-template').value;
    if (!newTemplate.trim()) {
        alert('プロンプトテンプレートを入力してください / Please enter a prompt template');
        return;
    }

    try {
        const response = await fetch(`/api/projects/${projectId}/revisions/latest`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                prompt_template: newTemplate
            })
        });

        if (!response.ok) throw new Error('Failed to save revision');

        const result = await response.json();
        closeModal();

        if (result.is_new) {
            alert(`新しいリビジョン ${result.revision} を作成しました / New revision ${result.revision} created`);
        } else {
            alert('変更がありませんでした / No changes detected');
        }
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Show batch edit parser modal
 * Enhanced with revision selector, restore button, and CSV converter (same as single execution)
 */
async function showBatchEditParserModal() {
    const selectValue = document.getElementById('batch-project-select').value;
    if (!selectValue) {
        alert('プロジェクトを選択してください / Please select a project');
        return;
    }

    const parsed = parseSelectValue(selectValue);
    if (!parsed || parsed.type !== 'project' || !parsed.id) {
        alert('プロジェクトを選択してください / Please select a project');
        return;
    }
    const projectId = parsed.id;

    try {
        // Fetch project and revisions in parallel
        const [projectResponse, revisionsResponse] = await Promise.all([
            fetch(`/api/projects/${projectId}`),
            fetch(`/api/projects/${projectId}/revisions`)
        ]);

        if (!projectResponse.ok) throw new Error('Failed to load project');
        const project = await projectResponse.json();
        const revisions = revisionsResponse.ok ? await revisionsResponse.json() : [];

        // Build revision selector options
        const revisionOptions = revisions.map(rev => {
            const date = formatJST(rev.created_at);
            const isCurrent = rev.revision === project.revision_count;
            return `<option value="${rev.revision}" ${isCurrent ? 'selected' : ''}>
                Rev.${rev.revision} (${date})${isCurrent ? ' - 現在' : ''}
            </option>`;
        }).join('');

        const parserConfig = project.parser_config || {type: 'none'};
        const parserJson = JSON.stringify(parserConfig, null, 2);

        const modalContent = `
            <div class="modal-header">
                パーサー設定編集 / Edit Parser Configuration
                <button onclick="showParserHelp()" style="background: none; border: none; cursor: pointer; font-size: 1.2rem; margin-left: 10px;" title="ヘルプを表示 / Show Help">❓</button>
            </div>
            <div class="modal-body">
                <div class="form-group">
                    <label>プロジェクト / Project: ${project.name}</label>
                </div>
                <div class="form-group" style="display: flex; align-items: center; gap: 10px;">
                    <label style="margin: 0;">リビジョン / Revision:</label>
                    <select id="batch-revision-selector" onchange="loadBatchRevisionContent(this.value, 'parser', ${projectId})" style="flex: 1;">
                        ${revisionOptions}
                    </select>
                    <button class="btn btn-secondary" onclick="restoreBatchRevision('parser', ${projectId})" style="background-color: #e67e22;" title="選択したリビジョンを復元 / Restore selected revision">
                        🔄 復元 / Restore
                    </button>
                </div>
                <div class="form-group">
                    <label>パーサータイプ / Parser Type:</label>
                    <select id="edit-parser-type">
                        <option value="none" ${parserConfig.type === 'none' ? 'selected' : ''}>なし / None</option>
                        <option value="json_path" ${parserConfig.type === 'json_path' ? 'selected' : ''}>JSON Path</option>
                        <option value="regex" ${parserConfig.type === 'regex' ? 'selected' : ''}>正規表現 / Regex</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>パーサー設定 (JSON) / Parser Configuration (JSON):</label>
                    <textarea id="edit-parser-config" rows="12" style="font-family: 'Courier New', monospace;">${parserJson}</textarea>
                    <small style="color: #7f8c8d;">
                        JSON Path例: {"type": "json_path", "paths": {"answer": "$.answer"}}<br>
                        正規表現例: {"type": "regex", "patterns": {"answer": "Answer: (.+)"}}
                    </small>
                </div>
            </div>
            <div class="modal-footer" style="display: flex; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem;">
                <button class="btn" onclick="showJsonToCsvConverter()" style="background-color: #9b59b6;">📊 結果からCSVに変換 / Convert JSON to CSV</button>
                <div style="display: flex; gap: 0.5rem;">
                    <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
                    <button class="btn btn-primary" onclick="saveBatchParserRevision(${projectId})">保存 / Save</button>
                </div>
            </div>
        `;
        showModal(modalContent);
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Save batch parser revision
 * Smart save: Creates new revision only if content changed
 */
async function saveBatchParserRevision(projectId) {
    const parserType = document.getElementById('edit-parser-type').value;
    const parserConfigText = document.getElementById('edit-parser-config').value;

    let parserConfig;
    try {
        parserConfig = JSON.parse(parserConfigText);
        parserConfig.type = parserType;
    } catch (error) {
        alert('パーサー設定のJSON形式が不正です / Invalid JSON format for parser configuration');
        return;
    }

    try {
        const response = await fetch(`/api/projects/${projectId}/revisions/latest`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                parser_config: JSON.stringify(parserConfig)
            })
        });

        if (!response.ok) throw new Error('Failed to save revision');

        const result = await response.json();
        closeModal();

        if (result.is_new) {
            alert(`新しいリビジョン ${result.revision} を作成しました / New revision ${result.revision} created`);
        } else {
            alert('変更がありませんでした / No changes detected');
        }
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Load revision content for batch editor
 * @param {number} revisionNumber - The revision number to load
 * @param {string} type - 'prompt' or 'parser'
 * @param {number} projectId - The project ID
 */
async function loadBatchRevisionContent(revisionNumber, type, projectId) {
    try {
        const response = await fetch(`/api/projects/${projectId}/revisions`);
        if (!response.ok) throw new Error('Failed to load revisions');

        const revisions = await response.json();
        const revision = revisions.find(r => r.revision === parseInt(revisionNumber));

        if (!revision) {
            alert('リビジョンが見つかりません / Revision not found');
            return;
        }

        if (type === 'prompt') {
            document.getElementById('edit-prompt-template').value = revision.prompt_template;
        } else if (type === 'parser') {
            const parserConfig = revision.parser_config ? JSON.parse(revision.parser_config) : {type: 'none'};
            document.getElementById('edit-parser-type').value = parserConfig.type || 'none';
            document.getElementById('edit-parser-config').value = JSON.stringify(parserConfig, null, 2);
        }
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Restore a past revision for batch editor (creates new revision with old content)
 * @param {string} type - 'prompt' or 'parser'
 * @param {number} projectId - The project ID
 */
async function restoreBatchRevision(type, projectId) {
    const selector = document.getElementById('batch-revision-selector');
    if (!selector) {
        alert('リビジョンセレクタが見つかりません / Revision selector not found');
        return;
    }

    const revisionNumber = parseInt(selector.value);
    const selectedOption = selector.options[selector.selectedIndex];
    const isCurrent = selectedOption.text.includes('現在');

    if (isCurrent) {
        alert('現在のリビジョンは復元できません（既に最新です）\nCannot restore current revision (already latest)');
        return;
    }

    if (!confirm(`リビジョン ${revisionNumber} を復元しますか？\n新しいリビジョンとして作成されます。\n\nRestore revision ${revisionNumber}?\nThis will create a new revision.`)) {
        return;
    }

    try {
        // Get the revision content
        const revisionsResponse = await fetch(`/api/projects/${projectId}/revisions`);
        if (!revisionsResponse.ok) throw new Error('Failed to load revisions');

        const revisions = await revisionsResponse.json();
        const revision = revisions.find(r => r.revision === revisionNumber);

        if (!revision) {
            alert('リビジョンが見つかりません / Revision not found');
            return;
        }

        // Create new revision with old content
        const restoreResponse = await fetch(`/api/projects/${projectId}/revisions/latest`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                prompt_template: revision.prompt_template,
                parser_config: revision.parser_config
            })
        });

        if (!restoreResponse.ok) throw new Error('Failed to restore revision');

        const result = await restoreResponse.json();
        closeModal();
        alert(`リビジョン ${revisionNumber} を復元しました（新しいリビジョン: ${result.revision}）\nRevision ${revisionNumber} restored (new revision: ${result.revision})`);
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

// ========== BATCH EXECUTION TAB ==========

async function loadBatchJobs() {
    // Load datasets and prompts for currently selected project (if any)
    const projectSelect = document.getElementById('batch-project-select');
    if (projectSelect && projectSelect.value) {
        const parsed = parseSelectValue(projectSelect.value);
        if (parsed && parsed.type === 'project' && parsed.id) {
            await loadDatasetsForProject(parsed.id);
            await loadBatchPromptsForProject(parsed.id);
            await loadBatchJobHistory(parsed.id);
        }
    }
}

async function loadBatchJobHistory(projectId) {
    try {
        // Reset pagination state for batch history
        batchHistoryOffset = 0;
        batchHistoryHasMore = true;

        // Get batch-type jobs for this project (first page only)
        const response = await fetch(`/api/projects/${projectId}/jobs?limit=${BATCH_HISTORY_PAGE_SIZE}&offset=0&job_type=batch`);
        const batchJobs = await response.json();

        // Update pagination state
        batchHistoryHasMore = batchJobs.length >= BATCH_HISTORY_PAGE_SIZE;
        batchHistoryOffset = batchJobs.length;

        renderBatchHistory(batchJobs);
    } catch (error) {
        const container = document.getElementById('batch-jobs-list');
        if (container) {
            container.innerHTML = '<p class="info">バッチジョブの履歴を読み込めませんでした / Failed to load batch job history</p>';
        }
    }
}

let currentBatchJobs = [];

function renderBatchHistory(jobs, append = false) {
    const container = document.getElementById('batch-jobs-list');
    if (!container) return;

    // Always remove existing "Load more" link first when appending
    if (append) {
        const existingLoadMore = container.querySelector('.load-more-link');
        if (existingLoadMore) {
            existingLoadMore.remove();
        }
    }

    // Store jobs for later use
    if (append) {
        currentBatchJobs = [...currentBatchJobs, ...(jobs || [])];
    } else {
        currentBatchJobs = jobs || [];
    }

    // Handle empty jobs
    if (!jobs || jobs.length === 0) {
        if (!append) {
            container.innerHTML = '<p class="info">バッチジョブの履歴はまだありません / No batch jobs yet</p>';
        }
        // When append mode with no new items, just update Load More button state
        if (append && batchHistoryHasMore) {
            container.insertAdjacentHTML('beforeend', `
                <div class="load-more-link" onclick="loadMoreBatchHistory()">
                    さらに表示 / Load more...
                </div>
            `);
        }
        return;
    }

    const jobsHtml = jobs.map(job => {
        const createdAt = formatJST(job.created_at);
        const finishedAt = formatJST(job.finished_at);
        const turnaround = job.turnaround_ms ? `${(job.turnaround_ms / 1000).toFixed(1)}s` : 'N/A';
        const itemCount = job.items ? job.items.length : 0;
        const modelName = job.model_name || '-';
        const promptName = job.prompt_name || '-';

        // Show delete button for pending/running jobs
        const canDelete = job.status === 'pending' || job.status === 'running';
        const deleteBtn = canDelete ?
            `<button class="delete-job-btn" onclick="event.stopPropagation(); deleteJob(${job.id}, 'batch')" title="ジョブを削除">🗑️</button>` : '';

        return `
            <div class="history-item" data-job-id="${job.id}">
                <div class="job-header">
                    <div class="job-id">Batch Job #${job.id} (${itemCount} items)</div>
                    ${deleteBtn}
                </div>
                <div class="prompt-info">🎯 ${promptName}</div>
                <div class="timestamp">実行: ${createdAt}</div>
                <div class="timestamp">完了: ${finishedAt}</div>
                <div class="turnaround">モデル: ${modelName} | 実行時間: ${turnaround}</div>
                <span class="status ${job.status}">${job.status}</span>
            </div>
        `;
    }).join('');

    // Add "Load more" link if there are more jobs
    const loadMoreHtml = batchHistoryHasMore ? `
        <div class="load-more-link" onclick="loadMoreBatchHistory()">
            さらに表示 / Load more...
        </div>
    ` : '';

    if (append) {
        container.insertAdjacentHTML('beforeend', jobsHtml + loadMoreHtml);
    } else {
        container.innerHTML = jobsHtml + loadMoreHtml;
    }

    // Add click event listeners after rendering
    document.querySelectorAll('#batch-jobs-list .history-item').forEach(item => {
        item.addEventListener('click', () => {
            const jobId = parseInt(item.dataset.jobId);
            selectBatchJob(jobId);
        });
    });
}

let batchHistoryLoading = false;

async function loadMoreBatchHistory() {
    // Prevent duplicate clicks while loading
    if (batchHistoryLoading) return;
    batchHistoryLoading = true;

    // Update button to show loading state
    const loadMoreBtn = document.querySelector('#batch-jobs-list .load-more-link');
    if (loadMoreBtn) {
        loadMoreBtn.textContent = '読み込み中... / Loading...';
        loadMoreBtn.style.pointerEvents = 'none';
    }

    try {
        const projectSelect = document.getElementById('batch-project-select');
        if (!projectSelect || !projectSelect.value) return;

        const parsed = parseSelectValue(projectSelect.value);
        if (!parsed || parsed.type !== 'project' || !parsed.id) return;

        // Fetch next page of batch-type jobs
        const response = await fetch(`/api/projects/${parsed.id}/jobs?limit=${BATCH_HISTORY_PAGE_SIZE}&offset=${batchHistoryOffset}&job_type=batch`);
        if (!response.ok) throw new Error('Failed to load more jobs');
        const batchJobs = await response.json();

        // Update pagination state BEFORE rendering
        batchHistoryHasMore = batchJobs.length >= BATCH_HISTORY_PAGE_SIZE;
        batchHistoryOffset += batchJobs.length;

        // Append to existing history (or update Load More button state)
        renderBatchHistory(batchJobs, true);
    } catch (error) {
        showStatus('履歴の読み込みに失敗しました / Failed to load more history', 'error');
    } finally {
        batchHistoryLoading = false;
    }
}

async function selectBatchJob(jobId) {
    try {
        // Save selected job ID for refresh functionality
        selectedBatchJobId = jobId;

        // Find job in current batch jobs list
        const job = currentBatchJobs.find(j => j.id === jobId);

        if (job) {
            displayBatchResult(job);
        }

        // Highlight selected item
        document.querySelectorAll('#batch-jobs-list .history-item').forEach(item => {
            if (parseInt(item.dataset.jobId) === jobId) {
                item.classList.add('selected');
            } else {
                item.classList.remove('selected');
            }
        });
    } catch (error) {
        // Silently handle errors - could log to server if needed
    }
}

function displayBatchResult(job) {
    const container = document.getElementById('batch-results-area');

    if (!container) {
        return;
    }

    // Clear existing content first
    container.innerHTML = '';

    // Pass the batch results container directly to avoid ID conflicts
    // This ensures results display in the batch tab, not the single execution tab
    displayJobResults(job, container);
}

async function executeBatch() {
    const selectValue = document.getElementById('batch-project-select').value;
    const promptSelectValue = document.getElementById('batch-prompt-select').value;
    const datasetId = document.getElementById('batch-dataset-select').value;
    const includeCsvHeader = document.getElementById('batch-include-csv-header')?.checked ?? true;
    const modelName = document.getElementById('batch-model-select').value;

    // Parse selection value
    const { type, id } = parseSelectValue(selectValue);

    if (!selectValue || !datasetId) {
        alert('プロジェクト/ワークフローとデータセットを選択してください / Please select project/workflow and dataset');
        return;
    }

    // For project execution, prompt must be selected
    if (type !== 'workflow' && !promptSelectValue) {
        alert('プロンプトを選択してください / Please select a prompt');
        return;
    }

    // Immediate feedback
    const executeBtn = document.getElementById('btn-batch-execute');
    const originalText = executeBtn.textContent;
    executeBtn.disabled = true;
    executeBtn.textContent = '実行中... / Executing...';
    executeBtn.style.background = '#95a5a6';

    // Show stop button
    document.getElementById('btn-stop-batch').style.display = 'inline-block';

    try {
        // Get model parameters from system settings
        const paramsResponse = await fetch(`/api/settings/models/${modelName}/parameters`);
        const paramsData = await paramsResponse.json();
        const modelParams = paramsData.active_parameters || {};

        if (type === 'workflow') {
            // Workflow batch execution - execute workflow for each dataset row
            await executeBatchWorkflow(id, parseInt(datasetId), modelName, modelParams.temperature || 0.7);
        } else if (promptSelectValue === 'all') {
            // All prompts execution - run all prompts against the dataset sequentially
            await executeBatchAllPrompts(id, parseInt(datasetId), includeCsvHeader, modelName, modelParams);
        } else {
            // Single prompt batch execution
            const response = await fetch('/api/run/batch', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    project_id: id,
                    prompt_id: parseInt(promptSelectValue),
                    dataset_id: parseInt(datasetId),
                    include_csv_header: includeCsvHeader,
                    model_name: modelName,
                    ...modelParams  // Include all model parameters from system settings
                })
            });

            if (!response.ok) throw new Error('Batch execution failed');

            const result = await response.json();

            // Store job ID for cancellation
            currentBatchJobId = result.job_id;

            // Display results immediately
            displayBatchResult(result.job);

            // Restore execute button (but keep stop button visible)
            executeBtn.disabled = false;
            executeBtn.textContent = originalText;
            executeBtn.style.background = '';

            // Start polling for job progress
            pollBatchJobProgress(result.job_id, id);
        }

    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
        // On error, restore button and hide stop button
        executeBtn.disabled = false;
        executeBtn.textContent = originalText;
        executeBtn.style.background = '';
        document.getElementById('btn-stop-batch').style.display = 'none';
        currentBatchJobId = null;
    }
}

/**
 * Execute batch for all prompts in a project
 * Uses server-side API that creates ALL jobs upfront, ensuring execution
 * continues even if browser is closed.
 */
async function executeBatchAllPrompts(projectId, datasetId, includeCsvHeader, modelName, modelParams, force = false) {
    const executeBtn = document.getElementById('btn-batch-execute');
    const originalText = executeBtn.textContent;

    try {
        executeBtn.textContent = '全プロンプト実行開始中... / Starting all prompts...';

        // Call server-side API that creates ALL jobs upfront
        const response = await fetch('/api/run/batch-all', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                project_id: projectId,
                dataset_id: datasetId,
                include_csv_header: includeCsvHeader,
                model_name: modelName,
                temperature: modelParams.temperature || 0.7,
                force: force
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to start batch-all execution');
        }

        const result = await response.json();

        // Check if there are running jobs and force=false
        if (result.has_running_jobs && !force) {
            // Restore button immediately
            executeBtn.textContent = originalText;
            executeBtn.disabled = false;

            // Show confirmation dialog
            const runningCount = result.running_jobs_count;
            const confirmed = confirm(
                `既に ${runningCount} 件の実行中/待機中ジョブがあります。\n` +
                `追加で新しいジョブを作成しますか？\n\n` +
                `There are already ${runningCount} running/pending jobs.\n` +
                `Do you want to add new jobs?`
            );

            if (confirmed) {
                // Re-call with force=true
                return await executeBatchAllPrompts(projectId, datasetId, includeCsvHeader, modelName, modelParams, true);
            } else {
                showStatus('実行をキャンセルしました / Execution cancelled', 'info');
                return;
            }
        }

        // Check if there are recently created jobs (within 5 minutes) and force=false
        if (result.has_recent_jobs && !force) {
            // Restore button immediately
            executeBtn.textContent = originalText;
            executeBtn.disabled = false;

            // Show confirmation dialog
            const recentCount = result.recent_jobs_count;
            const confirmed = confirm(
                `過去5分以内に ${recentCount} 件のジョブが作成されています。\n` +
                `追加で新しいジョブを作成しますか？\n\n` +
                `${recentCount} jobs were created in the last 5 minutes.\n` +
                `Do you want to add new jobs?`
            );

            if (confirmed) {
                // Re-call with force=true
                return await executeBatchAllPrompts(projectId, datasetId, includeCsvHeader, modelName, modelParams, true);
            } else {
                showStatus('実行をキャンセルしました / Execution cancelled', 'info');
                return;
            }
        }

        const jobIds = result.job_ids;
        const jobs = result.jobs;

        // Store first job ID for potential cancellation
        if (jobIds.length > 0) {
            currentBatchJobId = jobIds[0];
        }

        // Show confirmation that all jobs are created
        executeBtn.textContent = `${jobIds.length} ジョブ作成完了 / ${jobIds.length} jobs created`;

        // Reload batch history immediately to show all created jobs
        await loadBatchJobHistory(projectId);

        // Poll for first job's progress (optional - just for UI feedback)
        // All jobs will execute on server even if browser is closed
        if (jobIds.length > 0) {
            pollBatchAllProgress(jobIds, projectId);
        }

        // Restore button after a short delay
        setTimeout(() => {
            executeBtn.textContent = originalText;
            executeBtn.disabled = false;
            executeBtn.style.background = '';
        }, 2000);

        // Show message about browser-independent execution
        showStatus(
            `${jobIds.length} 件のバッチジョブを作成しました。サーバー上で順次実行されます（ブラウザを閉じても実行継続） / ` +
            `${jobIds.length} batch jobs created. They will execute on server (continues even if browser is closed)`,
            'success'
        );

    } catch (error) {
        throw error;
    }
}

/**
 * Poll progress for batch-all execution (optional UI feedback)
 * Jobs will complete on server regardless of this polling
 */
async function pollBatchAllProgress(jobIds, projectId) {
    const executeBtn = document.getElementById('btn-batch-execute');
    let completedCount = 0;

    const checkInterval = setInterval(async () => {
        try {
            const response = await fetch(`/api/projects/${projectId}/jobs?job_type=batch&limit=${jobIds.length * 2}`);
            if (!response.ok) return;

            const jobs = await response.json();

            // Count completed jobs from our batch (including cancelled)
            completedCount = 0;
            for (const jobId of jobIds) {
                const job = jobs.find(j => j.id === jobId);
                if (job && (job.status === 'done' || job.status === 'error' || job.status === 'cancelled')) {
                    completedCount++;
                }
            }

            // Update UI
            if (completedCount < jobIds.length) {
                executeBtn.textContent = `実行中 ${completedCount}/${jobIds.length}... / Running ${completedCount}/${jobIds.length}...`;
            }

            // All done - reload history and stop polling
            if (completedCount >= jobIds.length) {
                clearInterval(checkInterval);
                await loadBatchJobHistory(projectId);
                executeBtn.textContent = '▶ バッチ実行開始 / Start Batch';
                executeBtn.disabled = false;
                executeBtn.style.background = '';
                document.getElementById('btn-stop-batch').style.display = 'none';
                currentBatchJobId = null;

                showStatus(
                    `全プロンプト実行完了！ ${jobIds.length} ジョブ完了 / All prompts executed! ${jobIds.length} jobs completed`,
                    'success'
                );
            }
        } catch (error) {
            console.error('Error polling batch-all progress:', error);
        }
    }, 3000); // Check every 3 seconds

    // Stop polling after 30 minutes max (jobs continue on server)
    setTimeout(() => {
        clearInterval(checkInterval);
    }, 30 * 60 * 1000);
}

/**
 * Wait for a batch job to complete (polling)
 */
async function waitForBatchJobCompletion(jobId, projectId) {
    return new Promise((resolve) => {
        const checkInterval = setInterval(async () => {
            try {
                const response = await fetch(`/api/projects/${projectId}/jobs`);
                const jobs = await response.json();
                const job = jobs.find(j => j.id === jobId);

                if (!job || job.status === 'done' || job.status === 'error' || job.status === 'cancelled') {
                    clearInterval(checkInterval);
                    resolve();
                }
            } catch (error) {
                console.error('Error checking job status:', error);
                clearInterval(checkInterval);
                resolve();
            }
        }, 2000); // Check every 2 seconds
    });
}

/**
 * Execute workflow in batch mode using dataset rows as input parameters
 * @param {number} workflowId - Workflow ID
 * @param {number} datasetId - Dataset ID
 * @param {string} modelName - Model name
 * @param {number} temperature - Temperature setting
 */
async function executeBatchWorkflow(workflowId, datasetId, modelName, temperature) {
    console.log(`🔄 Executing workflow ${workflowId} in batch mode with dataset ${datasetId}`);

    const executeBtn = document.getElementById('btn-batch-execute');
    const originalText = executeBtn.textContent;

    try {
        // Fetch dataset data
        const datasetResponse = await fetch(`/api/datasets/${datasetId}`);
        if (!datasetResponse.ok) throw new Error('Failed to load dataset');
        const dataset = await datasetResponse.json();

        if (!dataset.data || dataset.data.length === 0) {
            throw new Error('データセットが空です / Dataset is empty');
        }

        const totalRows = dataset.data.length;
        const workflowJobIds = [];

        // Create a results container
        const container = document.getElementById('batch-result');
        if (container) {
            container.innerHTML = `
                <div class="batch-progress">
                    <h4>ワークフローバッチ実行中... / Workflow Batch Execution...</h4>
                    <div id="workflow-batch-progress">0 / ${totalRows} 完了</div>
                    <div id="workflow-batch-jobs"></div>
                </div>
            `;
        }

        // Execute workflow for each row in the dataset
        for (let i = 0; i < totalRows; i++) {
            const row = dataset.data[i];

            // Update progress
            const progressEl = document.getElementById('workflow-batch-progress');
            if (progressEl) {
                progressEl.textContent = `${i + 1} / ${totalRows} 実行中...`;
            }

            executeBtn.textContent = `実行中... (${i + 1}/${totalRows})`;

            // Execute workflow with row data as input params
            const requestBody = {
                input_params: row,
                model_name: modelName,
                temperature: temperature
            };

            const response = await fetch(`/api/workflows/${workflowId}/run`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(requestBody)
            });

            if (!response.ok) {
                console.error(`Failed to execute workflow for row ${i + 1}`);
                continue;
            }

            const result = await response.json();
            workflowJobIds.push(result.id);

            // Add to jobs list
            const jobsEl = document.getElementById('workflow-batch-jobs');
            if (jobsEl) {
                jobsEl.innerHTML += `
                    <div class="workflow-batch-job" onclick="selectWorkflowJob(${result.id})">
                        <span>Row ${i + 1}: WF-Job #${result.id}</span>
                        <span class="status-pending">pending</span>
                    </div>
                `;
            }

            // Small delay between executions to avoid overwhelming the API
            await new Promise(resolve => setTimeout(resolve, 200));
        }

        // Update final progress
        const progressEl = document.getElementById('workflow-batch-progress');
        if (progressEl) {
            progressEl.textContent = `${totalRows} / ${totalRows} 完了！ジョブをポーリング中...`;
        }

        // Start polling for all workflow jobs
        pollWorkflowBatchJobs(workflowJobIds);

        showStatus(`ワークフローバッチ実行開始！ ${totalRows} 件のジョブを作成しました`, 'success');

    } finally {
        // Restore button
        executeBtn.disabled = false;
        executeBtn.textContent = originalText;
        executeBtn.style.background = '';
    }
}

/**
 * Poll multiple workflow batch jobs for completion
 * @param {Array<number>} jobIds - Array of workflow job IDs
 */
async function pollWorkflowBatchJobs(jobIds) {
    const pollInterval = setInterval(async () => {
        let allComplete = true;
        let completedCount = 0;

        for (const jobId of jobIds) {
            try {
                const response = await fetch(`/api/workflow-jobs/${jobId}`);
                if (!response.ok) continue;

                const job = await response.json();

                // Update status in UI
                const jobElements = document.querySelectorAll(`.workflow-batch-job`);
                jobElements.forEach(el => {
                    if (el.textContent.includes(`WF-Job #${jobId}`)) {
                        const statusEl = el.querySelector('span:last-child');
                        if (statusEl) {
                            statusEl.className = `status-${job.status}`;
                            statusEl.textContent = job.status;
                        }
                    }
                });

                if (job.status === 'completed' || job.status === 'error') {
                    completedCount++;
                } else {
                    allComplete = false;
                }
            } catch (error) {
                console.error(`Failed to poll job ${jobId}:`, error);
            }
        }

        // Update progress
        const progressEl = document.getElementById('workflow-batch-progress');
        if (progressEl) {
            progressEl.textContent = `${completedCount} / ${jobIds.length} 完了`;
        }

        if (allComplete) {
            clearInterval(pollInterval);
            document.getElementById('btn-stop-batch').style.display = 'none';
            showStatus('ワークフローバッチ実行完了！', 'success');
        }
    }, 3000);
}

// Poll batch job progress until completion
let batchPollIntervalId = null;

async function pollBatchJobProgress(jobId, projectId) {
    // Clear any existing polling interval
    if (batchPollIntervalId) {
        clearInterval(batchPollIntervalId);
    }

    // Poll every 3 seconds
    batchPollIntervalId = setInterval(async () => {
        try {
            // Fetch updated job data
            const response = await fetch(`/api/projects/${projectId}/jobs`);
            const allJobs = await response.json();
            const job = allJobs.find(j => j.id === jobId);

            if (!job) {
                // Job not found, stop polling
                clearInterval(batchPollIntervalId);
                batchPollIntervalId = null;
                hideBatchStopButton();
                return;
            }

            // Update display with latest job data
            displayBatchResult(job);

            // Check if job is complete (including cancelled)
            const isComplete = job.status === 'done' || job.status === 'error' || job.status === 'cancelled';
            const allItemsComplete = job.items && job.items.every(item =>
                item.status === 'done' || item.status === 'error' || item.status === 'cancelled'
            );

            if (isComplete || allItemsComplete) {
                // Job finished, stop polling
                clearInterval(batchPollIntervalId);
                batchPollIntervalId = null;
                hideBatchStopButton();
                // Reload history to show final status
                await loadBatchJobHistory(projectId);
            }
        } catch (error) {
            console.error('Error polling batch job:', error);
            // Continue polling on error (network issue might be temporary)
        }
    }, 3000); // Poll every 3 seconds
}

function hideBatchStopButton() {
    document.getElementById('btn-stop-batch').style.display = 'none';
    currentBatchJobId = null;
}

async function onBatchProjectChange(e) {
    const selectValue = e.target.value;
    const { type, id } = parseSelectValue(selectValue);

    if (type === 'workflow') {
        // For workflows, load datasets from the first step's project
        await loadDatasetsForWorkflow(id);
        // Clear prompt selector for workflows (not applicable)
        const promptSelect = document.getElementById('batch-prompt-select');
        if (promptSelect) {
            promptSelect.innerHTML = '<option value="">ワークフローでは不要 / Not needed for workflow</option>';
            promptSelect.disabled = true;
        }
        // Clear batch job history for workflows (TODO: implement workflow job history)
        const historyContainer = document.getElementById('batch-jobs-list');
        if (historyContainer) {
            historyContainer.innerHTML = '<p class="info">ワークフロージョブ履歴は準備中 / Workflow job history coming soon</p>';
        }
    } else {
        // Load datasets, prompts, and job history in parallel
        await Promise.all([
            loadDatasetsForProject(id),
            loadBatchPromptsForProject(id),
            loadBatchJobHistory(id)
        ]);
        const promptSelect = document.getElementById('batch-prompt-select');
        if (promptSelect) promptSelect.disabled = false;
    }
}

/**
 * Load prompts for batch execution project selector
 * Includes "All Prompts" option for running all prompts against dataset
 */
async function loadBatchPromptsForProject(projectId) {
    const select = document.getElementById('batch-prompt-select');
    if (!select) return;

    try {
        const response = await fetch(`/api/projects/${projectId}/prompts`);
        if (!response.ok) throw new Error('Failed to load prompts');
        const prompts = await response.json();

        let options = '<option value="">プロンプトを選択 / Select Prompt</option>';

        if (prompts.length > 1) {
            // Add "All Prompts" option only if there are multiple prompts
            options += `<option value="all">🔄 全プロンプト実行 / Run All Prompts (${prompts.length})</option>`;
        }

        prompts.forEach(prompt => {
            options += `<option value="${prompt.id}">${prompt.name}</option>`;
        });

        select.innerHTML = options;

        // Auto-select first prompt if only one
        if (prompts.length === 1) {
            select.value = prompts[0].id;
        }
    } catch (error) {
        console.error('Failed to load prompts for batch:', error);
        select.innerHTML = '<option value="">エラー / Error</option>';
    }
}

/**
 * Load datasets for workflow's first step project
 * @param {number} workflowId - Workflow ID
 */
async function loadDatasetsForWorkflow(workflowId) {
    try {
        // Get workflow details
        const workflowResponse = await fetch(`/api/workflows/${workflowId}`);
        if (!workflowResponse.ok) throw new Error('Failed to load workflow');
        const workflow = await workflowResponse.json();

        // Get first step's project ID
        if (workflow.steps && workflow.steps.length > 0) {
            const firstStepProjectId = workflow.steps[0].project_id;
            // Load datasets for the first step's project
            await loadDatasetsForProject(firstStepProjectId);
        } else {
            // No steps, show empty dataset list
            const select = document.getElementById('batch-dataset-select');
            if (select) {
                select.innerHTML = '<option value="">ステップがありません / No steps</option>';
            }
        }
    } catch (error) {
        console.error('Failed to load datasets for workflow:', error);
        const select = document.getElementById('batch-dataset-select');
        if (select) {
            select.innerHTML = '<option value="">エラー / Error</option>';
        }
    }
}

async function loadDatasetsForProject(projectId) {
    try {
        const response = await fetch(`/api/datasets?project_id=${projectId}`);
        const datasets = await response.json();

        const select = document.getElementById('batch-dataset-select');
        if (!select) return;

        select.innerHTML = '<option value="">データセットを選択 / Select Dataset</option>' +
            datasets.map(ds => `<option value="${ds.id}">${ds.name} (${ds.row_count} rows)</option>`).join('');
    } catch (error) {
        // Failed to load datasets - silently continue
    }
}

// ========== PROJECTS TAB ==========

async function loadProjects() {
    try {
        // Load both projects and workflows in parallel
        const [projectsResponse, workflowsResponse] = await Promise.all([
            fetch('/api/projects'),
            fetch('/api/workflows')
        ]);

        allProjects = await projectsResponse.json();

        // Load workflows (may not exist yet, handle gracefully)
        if (workflowsResponse.ok) {
            allWorkflows = await workflowsResponse.json();
        } else {
            allWorkflows = [];
        }

        renderProjects();
        await updateProjectSelects();
    } catch (error) {
        // Failed to load projects - silently continue
        console.error('Failed to load projects/workflows:', error);
    }
}

function renderProjects() {
    const container = document.getElementById('projects-list');
    if (!container) return;

    if (allProjects.length === 0) {
        container.innerHTML = '<p class="info">プロジェクトがありません / No projects</p>';
        return;
    }

    container.innerHTML = allProjects.map(project => `
        <div class="list-item">
            <div class="item-header">
                <div class="item-title">${project.name}</div>
                <div class="item-actions">
                    <button class="btn btn-secondary" onclick="editProject(${project.id})">編集 / Edit</button>
                    <button class="btn btn-secondary" onclick="deleteProject(${project.id})">削除 / Delete</button>
                </div>
            </div>
            <div class="item-description">${project.description || ''}</div>
            <div class="item-meta">
                リビジョン数: ${project.revision_count} | 作成日: ${formatJST(project.created_at)}
            </div>
        </div>
    `).join('');
}

async function updateProjectSelects() {
    const singleSelect = document.getElementById('single-project-select');
    const batchSelect = document.getElementById('batch-project-select');
    const defaultProjectSelect = document.getElementById('default-project-select');

    // Build project options (no workflows - workflows are now selected in prompt/target selector)
    const projectOptions = allProjects.map(p => `<option value="project-${p.id}">${p.name}</option>`).join('');

    // Plain project options for settings (no workflows)
    const plainProjectOptions = allProjects.map(p => `<option value="${p.id}">${p.name}</option>`).join('');

    if (singleSelect) {
        singleSelect.innerHTML = projectOptions;
        // Set default project if configured
        let defaultLoaded = false;
        try {
            const response = await fetch('/api/settings/default-project');
            const data = await response.json();
            if (data.project_id) {
                singleSelect.value = `project-${data.project_id}`;
                currentProjectId = data.project_id;
                currentSelectionType = 'project';
                currentWorkflowId = null;
                // Trigger project change to load prompts
                await onProjectChange();
                defaultLoaded = true;
            }
        } catch (error) {
            console.error('Failed to load default project:', error);
        }

        // Fallback: if no default project, load execution targets for first project in list
        if (!defaultLoaded && singleSelect.value) {
            const { type, id } = parseSelectValue(singleSelect.value);
            if (type === 'project') {
                currentProjectId = id;
                currentSelectionType = 'project';
                currentWorkflowId = null;
                currentPromptId = null;
                // NEW ARCHITECTURE: Load execution targets instead of loadConfig
                await loadExecutionTargets(id);
            }
        }
    }

    if (batchSelect) {
        batchSelect.innerHTML = projectOptions;
        // Set default project if configured
        try {
            const response = await fetch('/api/settings/default-project');
            const data = await response.json();
            if (data.project_id) {
                batchSelect.value = `project-${data.project_id}`;
                // Load datasets for default project
                await loadDatasetsForProject(data.project_id);
            } else if (batchSelect.value) {
                // Auto-load datasets for first selection on batch tab if no default
                const { type, id } = parseSelectValue(batchSelect.value);
                if (type === 'project') {
                    await loadDatasetsForProject(id);
                }
            }
        } catch (error) {
            console.error('Failed to load default project for batch:', error);
            // Fallback to first selection
            if (batchSelect.value) {
                const { type, id } = parseSelectValue(batchSelect.value);
                if (type === 'project') {
                    await loadDatasetsForProject(id);
                }
            }
        }
    }

    if (defaultProjectSelect) {
        // Settings dropdown only shows projects, not workflows
        defaultProjectSelect.innerHTML = plainProjectOptions;
        // Set current default project in settings
        try {
            const response = await fetch('/api/settings/default-project');
            const data = await response.json();
            if (data.project_id) {
                defaultProjectSelect.value = data.project_id;
            }
        } catch (error) {
            console.error('Failed to load default project for settings:', error);
        }
    }
}

/**
 * Parse select value to extract type and ID
 * @param {string} value - Value in format "project-{id}" or "workflow-{id}"
 * @returns {{type: string, id: number}}
 */
function parseSelectValue(value) {
    if (!value) return { type: null, id: null };

    if (value.startsWith('workflow-')) {
        return { type: 'workflow', id: parseInt(value.replace('workflow-', '')) };
    } else if (value.startsWith('project-')) {
        return { type: 'project', id: parseInt(value.replace('project-', '')) };
    } else {
        // Legacy format - assume project ID
        return { type: 'project', id: parseInt(value) };
    }
}

function showCreateProjectModal() {
    showModal(`
        <div class="modal-header">新規プロジェクト作成 / Create Project</div>
        <div class="modal-body">
            <div class="form-group">
                <label>プロジェクト名 / Name:</label>
                <input type="text" id="project-name" required>
            </div>
            <div class="form-group">
                <label>説明 / Description:</label>
                <textarea id="project-description" rows="3"></textarea>
            </div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
            <button class="btn btn-primary" onclick="createProject()">作成 / Create</button>
        </div>
    `);
}

async function createProject() {
    const name = document.getElementById('project-name').value;
    const description = document.getElementById('project-description').value;

    if (!name) {
        alert('プロジェクト名を入力してください / Please enter project name');
        return;
    }

    try {
        const response = await fetch('/api/projects', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name, description})
        });

        if (!response.ok) throw new Error('Failed to create project');

        closeModal();
        await loadProjects();
        alert('プロジェクトを作成しました / Project created');
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

async function editProject(id) {
    const project = allProjects.find(p => p.id === id);
    if (!project) return;

    showModal(`
        <div class="modal-header">プロジェクト編集 / Edit Project</div>
        <div class="modal-body">
            <div class="form-group">
                <label>プロジェクト名 / Name:</label>
                <input type="text" id="edit-project-name" value="${project.name}" required>
            </div>
            <div class="form-group">
                <label>説明 / Description:</label>
                <textarea id="edit-project-description" rows="3">${project.description || ''}</textarea>
            </div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
            <button class="btn btn-primary" onclick="updateProject(${id})">更新 / Update</button>
        </div>
    `);
}

async function updateProject(id) {
    const name = document.getElementById('edit-project-name').value;
    const description = document.getElementById('edit-project-description').value;

    try {
        const response = await fetch(`/api/projects/${id}`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name, description})
        });

        if (!response.ok) throw new Error('Failed to update project');

        closeModal();
        await loadProjects();
        alert('プロジェクトを更新しました / Project updated');
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

async function deleteProject(id) {
    if (!confirm('このプロジェクトを削除しますか？ / Delete this project?')) return;

    try {
        const response = await fetch(`/api/projects/${id}`, {method: 'DELETE'});
        if (!response.ok) throw new Error('Failed to delete project');

        await loadProjects();
        alert('プロジェクトを削除しました / Project deleted');
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

// ========== SYSTEM SETTINGS TAB ==========

async function loadAvailableModels() {
    try {
        const response = await fetch('/api/settings/models/available');
        const models = await response.json();

        const container = document.getElementById('available-models');
        if (!container) return;

        container.innerHTML = models.map(model =>
            `<div class="badge badge-info">${model.display_name || model.name || model}</div>`
        ).join(' ');

        // Also load model configuration settings
        await loadModelConfigurationSettings();
    } catch (error) {
        // Failed to load models - silently continue
    }
}

/**
 * Load unified model configuration settings
 * Shows enable/disable toggle and parameters for each model
 */
async function loadModelConfigurationSettings() {
    const container = document.getElementById('model-configuration-settings');
    if (!container) return;

    try {
        // Load all models with their status
        const modelsResponse = await fetch('/api/settings/models/all');
        const models = await modelsResponse.json();

        // Load parameters for each model
        const modelsWithParams = await Promise.all(
            models.map(async (model) => {
                try {
                    const paramsResponse = await fetch(`/api/settings/models/${model.name}/parameters`);
                    if (!paramsResponse.ok) return { ...model, parameters: null };
                    const paramsData = await paramsResponse.json();
                    return {
                        ...model,
                        parameters: paramsData.active_parameters || paramsData.default_parameters || {},
                        defaultParameters: paramsData.default_parameters || {}
                    };
                } catch (e) {
                    return { ...model, parameters: null };
                }
            })
        );

        container.innerHTML = modelsWithParams.map(model => {
            const isAzureGPT5 = model.name.includes('azure-gpt-5');
            const isOpenAIGPT5 = model.name.includes('openai-gpt-5');
            const params = model.parameters || {};
            const defaultParams = model.defaultParameters || {};

            // Build parameter inputs based on model type
            let paramInputs = '';

            // Azure GPT-5 models: show max_output_tokens
            if (isAzureGPT5) {
                const maxTokens = params.max_output_tokens || defaultParams.max_output_tokens || 8192;
                paramInputs = `
                    <div style="display: flex; align-items: center; gap: 0.5rem; margin-top: 0.5rem; flex-wrap: wrap;">
                        <span style="color: #7f8c8d; font-size: 0.85rem; min-width: 130px;">max_output_tokens:</span>
                        <input type="number"
                               id="param-max_output_tokens-${model.name}"
                               value="${maxTokens}"
                               min="1024"
                               max="65536"
                               step="1024"
                               style="width: 100px;">
                        <button class="btn btn-primary btn-sm"
                                onclick="saveModelParameter('${model.name}', 'max_output_tokens')"
                                style="padding: 0.25rem 0.5rem; font-size: 0.8rem;">
                            保存
                        </button>
                        <span id="param-status-${model.name}" style="color: #27ae60; font-size: 0.85rem;"></span>
                    </div>
                `;
            }
            // OpenAI GPT-5 models: show verbosity and reasoning_effort
            else if (isOpenAIGPT5) {
                const verbosity = params.verbosity || defaultParams.verbosity || 'medium';
                const reasoningEffort = params.reasoning_effort || defaultParams.reasoning_effort || 'minimal';
                paramInputs = `
                    <div style="display: flex; align-items: center; gap: 0.5rem; margin-top: 0.5rem; flex-wrap: wrap;">
                        <span style="color: #7f8c8d; font-size: 0.85rem; min-width: 80px;">verbosity:</span>
                        <select id="param-verbosity-${model.name}" style="width: 100px;">
                            <option value="low" ${verbosity === 'low' ? 'selected' : ''}>low</option>
                            <option value="medium" ${verbosity === 'medium' ? 'selected' : ''}>medium</option>
                            <option value="high" ${verbosity === 'high' ? 'selected' : ''}>high</option>
                        </select>
                        <span style="color: #7f8c8d; font-size: 0.85rem; min-width: 110px; margin-left: 0.5rem;">reasoning_effort:</span>
                        <select id="param-reasoning_effort-${model.name}" style="width: 100px;">
                            <option value="minimal" ${reasoningEffort === 'minimal' ? 'selected' : ''}>minimal</option>
                            <option value="medium" ${reasoningEffort === 'medium' ? 'selected' : ''}>medium</option>
                        </select>
                        <button class="btn btn-primary btn-sm"
                                onclick="saveOpenAIGPT5Parameters('${model.name}')"
                                style="padding: 0.25rem 0.5rem; font-size: 0.8rem; margin-left: 0.5rem;">
                            保存
                        </button>
                        <span id="param-status-${model.name}" style="color: #27ae60; font-size: 0.85rem;"></span>
                    </div>
                `;
            }
            // GPT-4 and other models: show temperature if available
            else if (params.temperature !== undefined || defaultParams.temperature !== undefined) {
                const temp = params.temperature !== undefined ? params.temperature : (defaultParams.temperature || 0.7);
                paramInputs = `
                    <div style="display: flex; align-items: center; gap: 0.5rem; margin-top: 0.5rem; flex-wrap: wrap;">
                        <span style="color: #7f8c8d; font-size: 0.85rem; min-width: 100px;">temperature:</span>
                        <input type="number"
                               id="param-temperature-${model.name}"
                               value="${temp}"
                               min="0"
                               max="2"
                               step="0.1"
                               style="width: 80px;">
                        <button class="btn btn-primary btn-sm"
                                onclick="saveModelParameter('${model.name}', 'temperature')"
                                style="padding: 0.25rem 0.5rem; font-size: 0.8rem;">
                            保存
                        </button>
                        <span id="param-status-${model.name}" style="color: #27ae60; font-size: 0.85rem;"></span>
                    </div>
                `;
            }

            return `
                <div class="model-config-item" style="padding: 0.75rem; border-bottom: 1px solid #ecf0f1;">
                    <div style="display: flex; align-items: center; justify-content: space-between;">
                        <label style="flex: 1; margin: 0; cursor: pointer; display: flex; align-items: center;">
                            <input type="checkbox"
                                   class="model-enable-checkbox"
                                   data-model-name="${model.name}"
                                   ${model.enabled ? 'checked' : ''}
                                   onchange="toggleModelEnabled('${model.name}', this.checked)"
                                   style="margin-right: 0.5rem; cursor: pointer; width: 18px; height: 18px;">
                            <strong>${model.display_name}</strong>
                            <span style="color: #7f8c8d; font-size: 0.85rem; margin-left: 0.5rem;">(${model.name})</span>
                        </label>
                        <span class="badge ${model.enabled ? 'badge-success' : 'badge-secondary'}" style="font-size: 0.75rem;">
                            ${model.enabled ? '有効' : '無効'}
                        </span>
                    </div>
                    ${paramInputs}
                </div>
            `;
        }).join('');

        // Add help text at bottom
        container.innerHTML += `
            <p class="info" style="margin-top: 1rem; font-size: 0.85rem; color: #7f8c8d;">
                <strong>Azure GPT-5:</strong> max_output_tokens 推奨値 8192〜16384（出力が切れる場合は増加）<br>
                <strong>OpenAI GPT-5:</strong> verbosity (low/medium/high), reasoning_effort (minimal/medium)<br>
                <strong>GPT-4:</strong> temperature 0.0〜2.0（低い値=確定的、高い値=創造的）
            </p>
        `;

    } catch (error) {
        container.innerHTML = '<p class="error">モデル設定の読み込みに失敗しました / Failed to load model settings</p>';
    }
}

/**
 * Toggle model enabled/disabled status
 */
async function toggleModelEnabled(modelName, enabled) {
    try {
        const response = await fetch(`/api/settings/models/${modelName}/enable?enabled=${enabled}`, {
            method: 'PUT'
        });

        if (!response.ok) {
            throw new Error('Failed to update model status');
        }

        // Reload model lists
        await loadAvailableModels();
        await loadModelConfigurationSettings();

    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
        // Reload to reset checkbox state
        await loadModelConfigurationSettings();
    }
}

/**
 * Save a single model parameter
 */
async function saveModelParameter(modelName, paramName) {
    const input = document.getElementById(`param-${paramName}-${modelName}`);
    const statusSpan = document.getElementById(`param-status-${modelName}`);

    if (!input) return;

    let value = parseFloat(input.value);
    if (paramName === 'max_output_tokens') {
        value = parseInt(input.value, 10);
        if (isNaN(value) || value < 1024 || value > 65536) {
            alert('max_output_tokens は 1024 から 65536 の間で指定してください');
            return;
        }
    } else if (paramName === 'temperature') {
        if (isNaN(value) || value < 0 || value > 2) {
            alert('temperature は 0 から 2 の間で指定してください');
            return;
        }
    }

    try {
        const response = await fetch(`/api/settings/models/${modelName}/parameters`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ [paramName]: value })
        });

        if (!response.ok) {
            throw new Error('Failed to save parameter');
        }

        // Show success feedback
        if (statusSpan) {
            statusSpan.textContent = '✓ 保存完了';
            setTimeout(() => { statusSpan.textContent = ''; }, 3000);
        }

    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Save OpenAI GPT-5 parameters (verbosity and reasoning_effort)
 */
async function saveOpenAIGPT5Parameters(modelName) {
    const verbositySelect = document.getElementById(`param-verbosity-${modelName}`);
    const reasoningSelect = document.getElementById(`param-reasoning_effort-${modelName}`);
    const statusSpan = document.getElementById(`param-status-${modelName}`);

    if (!verbositySelect || !reasoningSelect) return;

    const verbosity = verbositySelect.value;
    const reasoningEffort = reasoningSelect.value;

    try {
        const response = await fetch(`/api/settings/models/${modelName}/parameters`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                verbosity: verbosity,
                reasoning_effort: reasoningEffort
            })
        });

        if (!response.ok) {
            throw new Error('Failed to save parameters');
        }

        // Show success feedback
        if (statusSpan) {
            statusSpan.textContent = '✓ 保存完了';
            setTimeout(() => { statusSpan.textContent = ''; }, 3000);
        }

    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

// ========== DATASETS TAB ==========

async function loadDatasets() {
    try {
        const response = await fetch('/api/datasets');
        allDatasets = await response.json();
        renderDatasets();
    } catch (error) {
        // Failed to load datasets - silently continue
    }
}

function renderDatasets() {
    const container = document.getElementById('datasets-list');
    if (!container) return;

    if (allDatasets.length === 0) {
        container.innerHTML = '<p class="info">データセットがありません / No datasets</p>';
        return;
    }

    container.innerHTML = allDatasets.map(dataset => `
        <div class="list-item">
            <div class="item-header">
                <div class="item-title">${dataset.name}</div>
                <div class="item-actions">
                    <button class="btn btn-secondary" onclick="previewDataset(${dataset.id})">プレビュー / Preview</button>
                    <button class="btn btn-secondary" onclick="deleteDataset(${dataset.id})">削除 / Delete</button>
                </div>
            </div>
            <div class="item-meta">
                ファイル: ${dataset.source_file_name} | 行数: ${dataset.row_count} | 作成日: ${formatJST(dataset.created_at)}
            </div>
        </div>
    `).join('');
}

function showImportDatasetModal() {
    showModal(`
        <div class="modal-header">データセットインポート / Import Dataset</div>
        <div class="modal-body">
            <div class="form-group">
                <label>プロジェクト / Project:</label>
                <select id="import-project-id">
                    ${allProjects.map(p => `<option value="${p.id}">${p.name}</option>`).join('')}
                </select>
            </div>
            <div class="form-group">
                <label>データセット名 / Dataset Name:</label>
                <input type="text" id="import-dataset-name" required>
            </div>
            <div class="form-group">
                <label>範囲名 / Range Name:</label>
                <input type="text" id="import-range-name" value="DSRange">
            </div>
            <div class="form-group">
                <label>Excelファイル / Excel File:</label>
                <input type="file" id="import-file" accept=".xlsx,.xls" required>
            </div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
            <button class="btn btn-primary" onclick="importDataset()">インポート / Import</button>
        </div>
    `);
}

async function importDataset() {
    const projectId = document.getElementById('import-project-id').value;
    const name = document.getElementById('import-dataset-name').value;
    const rangeName = document.getElementById('import-range-name').value;
    const fileInput = document.getElementById('import-file');

    if (!name || !fileInput.files[0]) {
        alert('すべての項目を入力してください / Please fill all fields');
        return;
    }

    const formData = new FormData();
    formData.append('project_id', projectId);
    formData.append('dataset_name', name);
    formData.append('range_name', rangeName);
    formData.append('file', fileInput.files[0]);

    try {
        const response = await fetch('/api/datasets/import', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Import failed');
        }

        closeModal();
        await loadDatasets();
        alert('データセットをインポートしました / Dataset imported');
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

async function previewDataset(id, showAll = false) {
    try {
        // Store dataset ID for toggle functionality
        currentPreviewDatasetId = id;

        // Fetch with limit=0 if showAll, otherwise default 10
        const limit = showAll ? 0 : 10;
        const response = await fetch(`/api/datasets/${id}/preview?limit=${limit}`);
        const preview = await response.json();

        // Helper function for escaping HTML in this context
        function escapeHtml(unsafe) {
            if (unsafe === null || unsafe === undefined) return '';
            return String(unsafe)
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        }

        const rowsHtml = preview.rows.map(row => {
            const cells = preview.columns.map(col => {
                const cellValue = row[col];
                const displayValue = escapeHtml(cellValue) || '';
                // Add title attribute for tooltip showing full content on hover
                const tooltipValue = String(cellValue ?? '').replace(/"/g, '&quot;');
                return `<td title="${tooltipValue}" style="border: 1px solid #ddd; padding: 8px;">${displayValue}</td>`;
            }).join('');
            return `<tr>${cells}</tr>`;
        }).join('');

        showModal(`
            <div class="modal-header" style="display: flex; justify-content: space-between; align-items: center;">
                <span>データセットプレビュー / Dataset Preview: ${preview.name}</span>
                <button onclick="closeModal()" style="background: none; border: none; font-size: 1.5rem; cursor: pointer; color: #7f8c8d; padding: 0 0.5rem;" title="閉じる / Close">×</button>
            </div>
            <div class="modal-body">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; gap: 0.5rem;">
                    <p style="margin: 0;">総行数 / Total Rows: ${preview.total_count}</p>
                    <div style="display: flex; gap: 1rem; flex-wrap: wrap;">
                        <label style="display: flex; align-items: center; gap: 0.3rem; cursor: pointer; user-select: none;">
                            <input type="checkbox" id="preview-show-all" ${showAll ? 'checked' : ''} onchange="togglePreviewShowAll(this.checked)">
                            <span style="font-size: 0.9rem;">全件表示 / Show All</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 0.3rem; cursor: pointer; user-select: none;">
                            <input type="checkbox" id="preview-truncate" checked onchange="togglePreviewTruncate(this.checked)">
                            <span style="font-size: 0.9rem;">折り返し省略 / Truncate</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 0.3rem; cursor: pointer; user-select: none;">
                            <input type="checkbox" id="preview-sticky-header" checked onchange="togglePreviewStickyHeader(this.checked)">
                            <span style="font-size: 0.9rem;">ヘッダ固定 / Fix Header</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 0.3rem; cursor: pointer; user-select: none;">
                            <input type="checkbox" id="preview-grid-lines" checked onchange="togglePreviewGridLines(this.checked)">
                            <span style="font-size: 0.9rem;">罫線表示 / Grid Lines</span>
                        </label>
                    </div>
                </div>
                <div id="preview-table-container" style="overflow-x: auto; max-height: 60vh; overflow-y: auto;">
                    <table id="preview-table" style="width: 100%; border-collapse: collapse;">
                        <thead>
                            <tr>${preview.columns.map(col => `<th style="border: 1px solid #ddd; padding: 8px; background: #f8f9fa;">${escapeHtml(col)}</th>`).join('')}</tr>
                        </thead>
                        <tbody>${rowsHtml}</tbody>
                    </table>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-primary" onclick="closeModal()">閉じる / Close</button>
            </div>
        `);

        // Apply default styles (all checkboxes checked by default)
        togglePreviewTruncate(true);
        togglePreviewStickyHeader(true);
        togglePreviewGridLines(true);
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Toggle truncate mode for dataset preview table
 */
function togglePreviewTruncate(enabled) {
    const table = document.getElementById('preview-table');
    if (!table) return;

    const cells = table.querySelectorAll('td');
    cells.forEach(cell => {
        if (enabled) {
            cell.style.maxWidth = '200px';
            cell.style.whiteSpace = 'nowrap';
            cell.style.overflow = 'hidden';
            cell.style.textOverflow = 'ellipsis';
        } else {
            cell.style.maxWidth = '';
            cell.style.whiteSpace = '';
            cell.style.overflow = '';
            cell.style.textOverflow = '';
        }
    });
}

/**
 * Toggle sticky header for dataset preview table
 */
function togglePreviewStickyHeader(enabled) {
    const table = document.getElementById('preview-table');
    if (!table) return;

    const thead = table.querySelector('thead');
    const headerCells = table.querySelectorAll('th');

    if (enabled) {
        thead.style.position = 'sticky';
        thead.style.top = '0';
        thead.style.zIndex = '10';
        headerCells.forEach(th => {
            th.style.background = '#f8f9fa';
            th.style.boxShadow = '0 2px 4px rgba(0,0,0,0.1)';
        });
    } else {
        thead.style.position = '';
        thead.style.top = '';
        thead.style.zIndex = '';
        headerCells.forEach(th => {
            th.style.boxShadow = '';
        });
    }
}

/**
 * Toggle grid lines and zebra striping for dataset preview table
 */
function togglePreviewGridLines(enabled) {
    const table = document.getElementById('preview-table');
    if (!table) return;

    const allCells = table.querySelectorAll('th, td');
    const rows = table.querySelectorAll('tbody tr');

    if (enabled) {
        // Add colored borders to all cells
        allCells.forEach(cell => {
            cell.style.border = '1px solid #3498db';
        });
        // Add zebra striping (odd rows get light blue background)
        rows.forEach((row, index) => {
            if (index % 2 === 0) {
                row.style.background = '#ebf5fb';
            } else {
                row.style.background = '#ffffff';
            }
        });
    } else {
        // Reset to default borders
        allCells.forEach(cell => {
            cell.style.border = '1px solid #ddd';
        });
        // Reset row backgrounds
        rows.forEach(row => {
            row.style.background = '';
        });
    }
}

/**
 * Toggle show all rows in dataset preview
 * Re-fetches the dataset with all rows or default limit
 */
function togglePreviewShowAll(showAll) {
    if (currentPreviewDatasetId) {
        previewDataset(currentPreviewDatasetId, showAll);
    }
}

// ========== DATASET ROW SELECTION FOR SINGLE EXECUTION ==========

/**
 * Show dataset selector modal for single execution
 * Step 1: User selects a dataset from the list
 */
function showDatasetSelectorForSingle() {
    // Filter datasets for current project
    const projectDatasets = allDatasets.filter(d => d.project_id === currentProjectId);

    if (projectDatasets.length === 0) {
        alert('このプロジェクトにはデータセットがありません。\nバッチ実行タブでデータセットをインポートしてください。\n\nNo datasets for this project.\nPlease import a dataset from the Batch Execution tab.');
        return;
    }

    const datasetListHtml = projectDatasets.map(dataset => `
        <div class="list-item" style="cursor: pointer; padding: 0.75rem; border: 1px solid #ddd; border-radius: 4px; margin-bottom: 0.5rem;"
             onclick="showDatasetRowSelector(${dataset.id})"
             onmouseover="this.style.background='#e8f4fc'"
             onmouseout="this.style.background=''">
            <div style="font-weight: bold;">${dataset.name}</div>
            <div style="font-size: 0.85rem; color: #666;">
                ファイル: ${dataset.source_file_name} | 行数: ${dataset.row_count}
            </div>
        </div>
    `).join('');

    showModal(`
        <div class="modal-header" style="display: flex; justify-content: space-between; align-items: center;">
            <span>データセットを選択 / Select Dataset</span>
            <button onclick="closeModal()" style="background: none; border: none; font-size: 1.5rem; cursor: pointer; color: #7f8c8d; padding: 0 0.5rem;" title="閉じる / Close">×</button>
        </div>
        <div class="modal-body">
            <p style="margin-bottom: 1rem; color: #666;">入力フォームに反映するデータセットを選択してください / Select a dataset to populate the input form</p>
            ${datasetListHtml}
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
        </div>
    `);
}

/**
 * Show dataset preview with selectable rows
 * Step 2: User selects a specific row from the dataset
 */
async function showDatasetRowSelector(datasetId, showAll = false) {
    try {
        currentPreviewDatasetId = datasetId;

        const limit = showAll ? 0 : 10;
        const response = await fetch(`/api/datasets/${datasetId}/preview?limit=${limit}`);
        const preview = await response.json();

        function escapeHtml(unsafe) {
            if (unsafe === null || unsafe === undefined) return '';
            return String(unsafe)
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        }

        // Create rows with selection capability (store row data as JSON in data attribute)
        const rowsHtml = preview.rows.map((row, index) => {
            const rowDataJson = encodeURIComponent(JSON.stringify(row));
            const cells = preview.columns.map(col => {
                const cellValue = row[col];
                const displayValue = escapeHtml(cellValue) || '';
                const tooltipValue = String(cellValue ?? '').replace(/"/g, '&quot;');
                return `<td title="${tooltipValue}" style="border: 1px solid #ddd; padding: 8px;">${displayValue}</td>`;
            }).join('');
            return `<tr class="selectable-row" data-row="${rowDataJson}" onclick="selectDatasetRow(this)"
                       style="cursor: pointer;"
                       onmouseover="this.style.background='#e8f4fc'"
                       onmouseout="this.style.background=''">${cells}</tr>`;
        }).join('');

        showModal(`
            <div class="modal-header" style="display: flex; justify-content: space-between; align-items: center;">
                <span>行を選択 / Select Row: ${preview.name}</span>
                <button onclick="closeModal()" style="background: none; border: none; font-size: 1.5rem; cursor: pointer; color: #7f8c8d; padding: 0 0.5rem;" title="閉じる / Close">×</button>
            </div>
            <div class="modal-body">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; gap: 0.5rem;">
                    <p style="margin: 0;">総行数 / Total Rows: ${preview.total_count} <span style="color: #666; font-size: 0.9rem;">（クリックで選択 / Click to select）</span></p>
                    <div style="display: flex; gap: 1rem; flex-wrap: wrap;">
                        <label style="display: flex; align-items: center; gap: 0.3rem; cursor: pointer; user-select: none;">
                            <input type="checkbox" id="row-select-show-all" ${showAll ? 'checked' : ''} onchange="toggleRowSelectorShowAll(this.checked)">
                            <span style="font-size: 0.9rem;">全件表示 / Show All</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 0.3rem; cursor: pointer; user-select: none;">
                            <input type="checkbox" id="row-select-truncate" checked onchange="togglePreviewTruncate(this.checked)">
                            <span style="font-size: 0.9rem;">折り返し省略 / Truncate</span>
                        </label>
                    </div>
                </div>
                <div id="preview-table-container" style="overflow-x: auto; max-height: 60vh; overflow-y: auto;">
                    <table id="preview-table" style="width: 100%; border-collapse: collapse;">
                        <thead>
                            <tr>${preview.columns.map(col => `<th style="border: 1px solid #ddd; padding: 8px; background: #f8f9fa;">${escapeHtml(col)}</th>`).join('')}</tr>
                        </thead>
                        <tbody>${rowsHtml}</tbody>
                    </table>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" onclick="showDatasetSelectorForSingle()">← 戻る / Back</button>
                <button class="btn btn-secondary" onclick="closeModal()">キャンセル / Cancel</button>
            </div>
        `);

        // Apply default styles
        togglePreviewTruncate(true);
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

/**
 * Toggle show all for row selector
 */
function toggleRowSelectorShowAll(showAll) {
    if (currentPreviewDatasetId) {
        showDatasetRowSelector(currentPreviewDatasetId, showAll);
    }
}

/**
 * Select a row from dataset and populate form
 * Step 3: Populate the input form with selected row data
 */
function selectDatasetRow(rowElement) {
    try {
        const rowDataJson = decodeURIComponent(rowElement.dataset.row);
        const rowData = JSON.parse(rowDataJson);

        // Populate form fields based on parameter names
        currentParameters.forEach(param => {
            const input = document.getElementById(`param-${param.name}`);
            if (input && rowData.hasOwnProperty(param.name)) {
                const value = rowData[param.name];

                // Handle different input types
                if (param.type === 'FILE' || param.type === 'FILEPATH' || param.type === 'TEXTFILEPATH') {
                    // For FILE/FILEPATH/TEXTFILEPATH types, set the value if it's a path string
                    if (typeof value === 'string' && value) {
                        input.value = value;
                    }
                } else if (input.tagName === 'TEXTAREA') {
                    input.value = value ?? '';
                } else if (input.type === 'number') {
                    input.value = value ?? '';
                } else if (input.type === 'date') {
                    // Convert date format if needed
                    if (value) {
                        const date = new Date(value);
                        if (!isNaN(date)) {
                            input.value = date.toISOString().split('T')[0];
                        } else {
                            input.value = value;
                        }
                    }
                } else if (input.type === 'datetime-local') {
                    // Convert datetime format if needed
                    if (value) {
                        const date = new Date(value);
                        if (!isNaN(date)) {
                            input.value = date.toISOString().slice(0, 16);
                        } else {
                            input.value = value;
                        }
                    }
                } else {
                    input.value = value ?? '';
                }
            }
        });

        closeModal();

        // Show success message briefly
        const statusDiv = document.getElementById('execution-status');
        if (statusDiv) {
            statusDiv.textContent = 'データセットから入力を反映しました / Form populated from dataset';
            statusDiv.className = 'status-message success';
            setTimeout(() => {
                statusDiv.textContent = '';
                statusDiv.className = 'status-message';
            }, 3000);
        }
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

async function deleteDataset(id) {
    if (!confirm('このデータセットを削除しますか？ / Delete this dataset?')) return;

    try {
        const response = await fetch(`/api/datasets/${id}`, {method: 'DELETE'});
        if (!response.ok) throw new Error('Failed to delete dataset');

        await loadDatasets();
        alert('データセットを削除しました / Dataset deleted');
    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

// ========== MODAL UTILITIES ==========

function showModal(content) {
    const modal = document.getElementById('modal-overlay');
    const modalContent = document.getElementById('modal-content');
    if (modal && modalContent) {
        modalContent.innerHTML = content;
        modal.classList.add('show');
    }
}

function closeModal() {
    const modal = document.getElementById('modal-overlay');
    if (modal) {
        modal.classList.remove('show');
    }
}

function showModal2(content) {
    const modal = document.getElementById('modal-overlay-2');
    const modalContent = document.getElementById('modal-content-2');
    if (modal && modalContent) {
        modalContent.innerHTML = content;
        modal.classList.add('show');
    }
}

function closeModal2() {
    const modal = document.getElementById('modal-overlay-2');
    if (modal) {
        modal.classList.remove('show');
    }
}

// Track which help tab is active
let currentHelpTab = 'prompt';

/**
 * Unified Help Modal - Shows both Prompt and Parser help with tabbed interface
 */
function showUnifiedHelp() {
    renderUnifiedHelp();
}

function renderUnifiedHelp() {
    const promptTabActive = currentHelpTab === 'prompt';
    const parserTabActive = currentHelpTab === 'parser';

    const promptHelpContent = `
        <h3 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem;">📖 プロンプトテンプレート構文 / Prompt Template Syntax</h3>
        <p style="margin: 1rem 0;">
            <code>{{ }}</code> で囲まれた部分がパラメータとして自動的に入力フォームに変換されます。
        </p>

        <h4 style="color: #27ae60; margin-top: 1rem;">基本構文 / Basic Syntax</h4>
        <pre style="background: #f8f9fa; padding: 0.8rem; border-radius: 4px; font-size: 0.9rem;"><code>{{PARAM_NAME:TYPE}}      必須パラメータ / Required
{{PARAM_NAME:TYPE|}}     任意パラメータ / Optional
{{PARAM_NAME:TYPE|default=値}} デフォルト値 / Default value</code></pre>

        <h4 style="color: #27ae60; margin-top: 1rem;">パラメータタイプ / Parameter Types</h4>
        <ul style="margin: 0.5rem 0 1rem 1.5rem; line-height: 1.8;">
            <li><strong>TEXT1〜TEXT20</strong>: テキストエリア（1〜20行）</li>
            <li><strong>NUM</strong>: 数値入力</li>
            <li><strong>DATE / DATETIME</strong>: 日付・日時選択</li>
            <li><strong>FILE</strong>: 画像アップロード（Vision API対応）</li>
            <li><strong>FILEPATH</strong>: サーバー画像パス（バッチ用）</li>
            <li><strong>TEXTFILEPATH</strong>: テキストファイルパス（内容展開）</li>
        </ul>

        <h4 style="color: #27ae60; margin-top: 1rem;">例 / Examples</h4>
        <pre style="background: #f8f9fa; padding: 0.8rem; border-radius: 4px; font-size: 0.85rem; white-space: pre-wrap;"><code>{{name:TEXT1}}           1行テキスト（必須）
{{description:TEXT5}}    5行テキストエリア（必須）
{{age:NUM|}}             数値入力（任意）
{{image:FILE}}           画像アップロード
{{file_path:FILEPATH}}   サーバー画像パス</code></pre>

        <div style="background: #e8f8f5; border-left: 4px solid #27ae60; padding: 0.8rem; margin: 1rem 0;">
            <strong>💡 ヒント:</strong> タイプを省略すると TEXT5（5行テキストエリア、必須）になります
        </div>
    `;

    const parserHelpContent = `
        <h3 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem;">📖 パーサー設定 / Parser Configuration</h3>
        <p style="margin: 1rem 0;">
            パーサーはLLMからの生レスポンスを構造化されたデータに変換します。CSV出力に必須です。
        </p>

        <h4 style="color: #27ae60; margin-top: 1rem;">1. JSON Path パーサー (推奨)</h4>
        <pre style="background: #f8f9fa; padding: 0.8rem; border-radius: 4px; font-size: 0.85rem;"><code>{
  "type": "json_path",
  "paths": {
    "answer": "$.answer",
    "score": "$.score"
  },
  "csv_template": "$answer$,$score$"
}</code></pre>

        <h4 style="color: #27ae60; margin-top: 1rem;">2. Regex パーサー</h4>
        <pre style="background: #f8f9fa; padding: 0.8rem; border-radius: 4px; font-size: 0.85rem;"><code>{
  "type": "regex",
  "patterns": {
    "answer": "Answer: (.+)",
    "score": "Score: (\\\\d+)"
  },
  "csv_template": "$answer$,$score$"
}</code></pre>

        <h4 style="color: #27ae60; margin-top: 1rem;">CSV出力設定</h4>
        <ul style="margin: 0.5rem 0 1rem 1.5rem; line-height: 1.8;">
            <li><code>csv_template</code>: CSV行の形式を指定</li>
            <li><code>$フィールド名$</code> の形式でフィールドを参照</li>
            <li>バッチ実行時に全結果がCSV形式に結合されます</li>
        </ul>

        <div style="background: #e8f8f5; border-left: 4px solid #27ae60; padding: 0.8rem; margin: 1rem 0;">
            <strong>💡 ヒント:</strong> プロンプトでLLMにJSON形式での出力を指示すると、パース精度が向上します
        </div>

        <div style="background: #fff3cd; border-left: 4px solid #ffc107; padding: 0.8rem; margin: 1rem 0;">
            <strong>⚠️ 注意:</strong> フィールド名は paths と csv_template で一致させてください
        </div>
    `;

    const helpContent = `
        <div class="modal-header" style="display: flex; justify-content: space-between; align-items: center;">
            <span style="font-weight: bold;">ヘルプ / Help</span>
            <button class="btn btn-secondary" onclick="closeModal2()" style="margin: 0; padding: 5px 15px;">閉じる / Close</button>
        </div>
        <div class="modal-body" style="max-height: 65vh; overflow-y: auto;">
            <!-- Tab Navigation -->
            <div style="display: flex; gap: 0; margin-bottom: 15px; border-bottom: 2px solid #007bff;">
                <button onclick="switchHelpTab('prompt')"
                    style="padding: 8px 20px; border: none; background: ${promptTabActive ? '#007bff' : '#e9ecef'}; color: ${promptTabActive ? 'white' : '#333'}; cursor: pointer; border-radius: 5px 5px 0 0; font-weight: ${promptTabActive ? 'bold' : 'normal'};">
                    プロンプト構文 / Prompt
                </button>
                <button onclick="switchHelpTab('parser')"
                    style="padding: 8px 20px; border: none; background: ${parserTabActive ? '#007bff' : '#e9ecef'}; color: ${parserTabActive ? 'white' : '#333'}; cursor: pointer; border-radius: 5px 5px 0 0; font-weight: ${parserTabActive ? 'bold' : 'normal'};">
                    パーサー設定 / Parser
                </button>
            </div>

            <!-- Help Content -->
            <div id="help-tab-content" style="min-height: 350px;">
                ${promptTabActive ? promptHelpContent : parserHelpContent}
            </div>
        </div>
    `;
    showModal2(helpContent);
}

function switchHelpTab(tab) {
    currentHelpTab = tab;
    renderUnifiedHelp();
}

function showParserHelp() {
    const helpContent = `
        <div class="modal-header" style="display: flex; justify-content: space-between; align-items: center;">
            <span>パーサー設定ヘルプ / Parser Configuration Help</span>
            <button class="btn btn-secondary" onclick="closeModal2()" style="margin: 0;">閉じる / Close</button>
        </div>
        <div class="modal-body" style="max-height: 70vh; overflow-y: auto;">
            <h3 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem;">📖 パーサー設定の概要 / Parser Configuration Overview</h3>
            <p style="margin: 1rem 0;">
                パーサーは、LLMからの生レスポンスを構造化されたデータに変換するための機能です。<br>
                特にCSV形式での出力を行う場合、パーサー設定が必須です。
            </p>
            <p style="margin: 1rem 0; font-style: italic; color: #7f8c8d;">
                The parser converts raw LLM responses into structured data.<br>
                Parser configuration is required for CSV output functionality.
            </p>

            <h3 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem; margin-top: 2rem;">🔧 パーサータイプ / Parser Types</h3>

            <h4 style="color: #27ae60; margin-top: 1rem;">1. JSON Path パーサー (推奨 / Recommended)</h4>
            <p><strong>用途:</strong> LLMがJSON形式でレスポンスを返す場合</p>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto;"><code>{
  "type": "json_path",
  "paths": {
    "answer": "$.answer",
    "confidence": "$.confidence",
    "category": "$.category"
  },
  "csv_template": "$answer$,$confidence$,$category$"
}</code></pre>
            <ul style="margin: 0.5rem 0 1rem 2rem;">
                <li><code>paths</code>: 抽出するフィールド名とJSONパス</li>
                <li><code>csv_template</code>: CSV行の形式（$フィールド名$で置換）</li>
            </ul>

            <h4 style="color: #27ae60; margin-top: 1rem;">2. Regex パーサー</h4>
            <p><strong>用途:</strong> LLMがテキスト形式でレスポンスを返す場合</p>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto;"><code>{
  "type": "regex",
  "patterns": {
    "answer": "Answer: (.+)",
    "score": "Score: (\\\\d+)"
  },
  "csv_template": "$answer$,$score$"
}</code></pre>
            <ul style="margin: 0.5rem 0 1rem 2rem;">
                <li><code>patterns</code>: 抽出するフィールド名と正規表現パターン</li>
                <li>正規表現のグループ ( ) でキャプチャした部分が値になります</li>
            </ul>

            <h3 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem; margin-top: 2rem;">📊 CSV出力設定 / CSV Output Configuration</h3>
            <p style="margin: 1rem 0;">
                <strong>csv_template</strong>を設定すると、バッチ実行時に全ての結果が自動的にCSV形式に結合されます。
            </p>
            <ul style="margin: 0.5rem 0 1rem 2rem;">
                <li><code>$フィールド名$</code>の形式でフィールドを参照</li>
                <li>カンマ区切りで複数フィールドを指定</li>
                <li>例: <code>"$name$,$age$,$city$"</code> → <code>John,30,Tokyo</code></li>
            </ul>
            <div style="background: #e8f8f5; border-left: 4px solid #27ae60; padding: 1rem; margin: 1rem 0;">
                <strong>💡 ヒント:</strong> バッチ実行時に「CSVヘッダを１行目のみに含める」にチェックを入れると、<br>
                1行目にフィールド名のヘッダーが自動的に追加されます。
            </div>

            <h3 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem; margin-top: 2rem;">🤖 LLMにパーサー構文を作成してもらう方法 / Using LLM to Generate Parser Config</h3>
            <p style="margin: 1rem 0;">プロンプトテンプレートに以下のような指示を追加すると、LLMが自動的にパース可能な形式で返答します：</p>

            <h4 style="color: #27ae60; margin-top: 1rem;">JSON形式の場合:</h4>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto;"><code>以下の質問に対して、必ず以下のJSON形式で回答してください：

{
  "answer": "あなたの回答",
  "confidence": "信頼度（0-1）",
  "category": "カテゴリ"
}

質問: {{question}}</code></pre>

            <h4 style="color: #27ae60; margin-top: 1rem;">テキスト形式の場合:</h4>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto;"><code>以下の質問に対して、必ず以下の形式で回答してください：

Answer: [あなたの回答]
Score: [スコア（0-100）]

質問: {{question}}</code></pre>

            <h3 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem; margin-top: 2rem;">✨ 完全な設定例 / Complete Configuration Example</h3>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto;"><code>{
  "type": "json_path",
  "paths": {
    "product_name": "$.product_name",
    "price": "$.price",
    "rating": "$.rating",
    "in_stock": "$.in_stock"
  },
  "csv_template": "$product_name$,$price$,$rating$,$in_stock$"
}</code></pre>
            <p style="margin: 1rem 0;">
                この設定により、バッチ実行で10件のデータを処理すると、<br>
                以下のような結合されたCSVが自動生成されます：
            </p>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto;"><code>product_name,price,rating,in_stock
Product A,1000,4.5,true
Product B,2000,4.2,false
...（全10行）</code></pre>

            <div style="background: #fff3cd; border-left: 4px solid #ffc107; padding: 1rem; margin: 1rem 0;">
                <strong>⚠️ 注意:</strong>
                <ul style="margin: 0.5rem 0 0 1rem;">
                    <li>フィールド名は<code>paths</code>と<code>csv_template</code>で一致させてください</li>
                    <li>JSON Pathは<code>$.</code>で始まります（例: <code>$.answer</code>）</li>
                    <li>CSV出力を使用する場合、<code>csv_template</code>は必須です</li>
                </ul>
            </div>
        </div>
    `;
    showModal2(helpContent);
}

function showPromptTemplateHelp() {
    const helpContent = `
        <div class="modal-header" style="display: flex; justify-content: space-between; align-items: center;">
            <span>プロンプトテンプレート構文ヘルプ / Prompt Template Syntax Help</span>
            <button class="btn btn-secondary" onclick="closeModal2()" style="margin: 0;">閉じる / Close</button>
        </div>
        <div class="modal-body" style="max-height: 75vh; overflow-y: auto; overflow-x: auto;">
            <h3 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem;">📖 プロンプトテンプレート構文の概要 / Prompt Template Syntax Overview</h3>
            <p style="margin: 1rem 0;">
                プロンプトテンプレートは、動的なパラメータを含むテキストです。<br>
                <code>{{ }}</code> で囲まれた部分がパラメータとして自動的に入力フォームに変換されます。
            </p>
            <p style="margin: 1rem 0; font-style: italic; color: #7f8c8d;">
                Prompt templates are text with dynamic parameters.<br>
                Parts enclosed in <code>{{ }}</code> are automatically converted to input forms.
            </p>

            <h3 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem; margin-top: 2rem;">📝 基本構文 / Basic Syntax</h3>

            <h4 style="color: #27ae60; margin-top: 1rem;">必須パラメータ / Required Parameters</h4>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto;"><code>{{PARAM_NAME:TYPE}}</code></pre>
            <ul style="margin: 0.5rem 0 1rem 2rem;">
                <li>ユーザーは必ず値を入力する必要があります / User must provide a value</li>
                <li>入力フォームに赤いアスタリスク (<span style="color: #e74c3c;">*</span>) が表示されます / Red asterisk displayed in form</li>
                <li>例 / Example: <code>{{name:TEXT1}}</code> → 1行テキスト入力（必須）</li>
            </ul>

            <h4 style="color: #27ae60; margin-top: 1rem;">任意パラメータ（デフォルト値なし）/ Optional Parameters (No Default)</h4>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto;"><code>{{PARAM_NAME:TYPE|}}</code></pre>
            <ul style="margin: 0.5rem 0 1rem 2rem;">
                <li><strong>重要:</strong> パラメータ名の後に <code>|</code> (パイプ) を付けます / Add <code>|</code> (pipe) after parameter name</li>
                <li>ユーザーは空欄のまま実行できます / User can leave blank</li>
                <li>アスタリスクは表示されません / No asterisk displayed</li>
                <li>例 / Example: <code>{{phone:TEXT1|}}</code> → 1行テキスト入力（任意、空欄可）</li>
            </ul>

            <h4 style="color: #27ae60; margin-top: 1rem;">任意パラメータ（デフォルト値あり）/ Optional Parameters (With Default)</h4>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto;"><code>{{PARAM_NAME:TYPE|default=値}}</code></pre>
            <ul style="margin: 0.5rem 0 1rem 2rem;">
                <li><code>|default=</code> の後にデフォルト値を指定 / Specify default value after <code>|default=</code></li>
                <li>ユーザーが空欄の場合、デフォルト値が使用されます / Default value used if left blank</li>
                <li>入力フォームに初期値として表示されます / Displayed as initial value in form</li>
                <li>例 / Example: <code>{{preferred_time:TEXT1|default=平日10-18時}}</code></li>
            </ul>

            <h4 style="color: #27ae60; margin-top: 1rem;">タイプ省略時のデフォルト / Default When Type Omitted</h4>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto;"><code>{{PARAM_NAME}}</code></pre>
            <ul style="margin: 0.5rem 0 1rem 2rem;">
                <li>タイプを省略すると、デフォルトで <code>TEXT5</code>（5行テキストエリア、必須）になります</li>
                <li>If type is omitted, defaults to <code>TEXT5</code> (5-line textarea, required)</li>
            </ul>

            <h3 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem; margin-top: 2rem;">📌 パラメータタイプ一覧 / Parameter Types</h3>

            <h4 style="color: #27ae60; margin-top: 1rem;">テキスト入力 / Text Input</h4>
            <ul style="margin: 0.5rem 0 1rem 2rem;">
                <li><strong>TEXT1 〜 TEXT20</strong>: テキストエリア（1〜20行）/ Textarea (1-20 lines)</li>
                <li>例 / Example: <code>{{description:TEXT5}}</code> → 5行のテキストエリア</li>
            </ul>

            <h4 style="color: #27ae60; margin-top: 1rem;">数値・日時入力 / Numeric & DateTime Input</h4>
            <ul style="margin: 0.5rem 0 1rem 2rem;">
                <li><strong>NUM</strong>: 数値入力 / Number input</li>
                <li><strong>DATE</strong>: 日付選択 / Date picker (YYYY-MM-DD)</li>
                <li><strong>DATETIME</strong>: 日時選択 / DateTime picker (YYYY-MM-DD HH:MM)</li>
            </ul>

            <h4 style="color: #27ae60; margin-top: 1rem;">画像・ファイル入力 / Image & File Input</h4>
            <ul style="margin: 0.5rem 0 1rem 2rem;">
                <li><strong>FILE</strong>: 画像アップロード（Vision API対応）/ Image upload (Vision API compatible)
                    <ul style="margin-top: 0.3rem;">
                        <li>対応形式 / Supported: JPEG, PNG, GIF, WebP</li>
                        <li>最大サイズ / Max size: 20MB</li>
                        <li>ブラウザから画像をアップロードして、LLMのVision APIに送信 / Upload from browser and send to Vision API</li>
                        <li>ドラッグ＆ドロップ対応 / Drag & drop supported</li>
                    </ul>
                </li>
                <li><strong>FILEPATH</strong>: サーバー画像ファイルパス（バッチ処理用）/ Server image file path (for batch processing)
                    <ul style="margin-top: 0.3rem;">
                        <li>サーバー上の画像ファイルパスを指定 / Specify image file path on server</li>
                        <li>バッチ実行時、データセットにファイルパスを記載して使用 / Use by specifying file paths in dataset for batch execution</li>
                    </ul>
                </li>
                <li><strong>TEXTFILEPATH</strong>: テキストファイルパス（内容をプロンプトに埋め込み）/ Text file path (content embedded in prompt)
                    <ul style="margin-top: 0.3rem;">
                        <li>サーバー上のテキストファイルパスを指定 / Specify text file path on server</li>
                        <li>ファイルの内容を読み込んでプロンプト本文に展開 / File content is read and embedded in prompt</li>
                        <li>UTF-8エンコーディングに対応 / Supports UTF-8 encoding</li>
                    </ul>
                </li>
            </ul>

            <h3 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 0.5rem; margin-top: 2rem;">✨ 実例 / Complete Examples</h3>

            <h4 style="color: #27ae60; margin-top: 1rem;">例1: お問い合わせフォーム / Example 1: Contact Form</h4>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto; white-space: pre-wrap;"><code>以下の情報に基づいてお問い合わせメールを作成してください。

【必須項目】
お名前: {{name:TEXT1}}
メールアドレス: {{email:TEXT1}}
お問い合わせ内容: {{inquiry:TEXT5}}

【任意項目】
電話番号: {{phone:TEXT1|}}
会社名: {{company:TEXT1|}}
希望連絡時間: {{preferred_time:TEXT1|default=平日10-18時}}
備考: {{notes:TEXT5|default=特になし}}</code></pre>

            <h4 style="color: #27ae60; margin-top: 1rem;">例2: 画像分析プロンプト / Example 2: Image Analysis Prompt</h4>
            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto; white-space: pre-wrap;"><code>添付された画像を分析してください。

画像ファイル: {{image:FILE}}
分析の観点: {{analysis_focus:TEXT1|default=全体的な内容と特徴}}

上記の観点で、画像の内容を詳しく説明してください。</code></pre>

            <div style="background: #e8f8f5; border-left: 4px solid #27ae60; padding: 1rem; margin: 1.5rem 0;">
                <strong>💡 ヒント / Tips:</strong>
                <ul style="margin: 0.5rem 0 0 1.5rem;">
                    <li>必須項目は最小限にして、ユーザーの入力負担を減らしましょう</li>
                    <li>Minimize required fields to reduce user input burden</li>
                    <li>デフォルト値を設定すると、入力の手間が省けます</li>
                    <li>Setting default values saves input effort</li>
                    <li>同じパラメータ名を複数箇所で使用すると、同じ値が展開されます</li>
                    <li>Using the same parameter name in multiple places expands to the same value</li>
                </ul>
            </div>
        </div>
    `;
    showModal2(helpContent);
}

// ========== SETTINGS MANAGEMENT ==========

let availableModelsData = [];
let currentModelParams = null;

async function loadSettings() {
    try {
        // Load available models
        const modelsResponse = await fetch('/api/settings/models/available');
        availableModelsData = await modelsResponse.json();

        // Populate all model selects
        populateModelSelects();

        // Load default model
        const defaultResponse = await fetch('/api/settings/models/default');
        const defaultData = await defaultResponse.json();
        document.getElementById('default-model-select').value = defaultData.default_model;

        // Set default model in execution dropdowns
        document.getElementById('model-select').value = defaultData.default_model;
        document.getElementById('batch-model-select').value = defaultData.default_model;

    } catch (error) {
        console.error('Failed to load settings:', error);
    }
}

function populateModelSelects() {
    const selects = [
        'model-select',
        'batch-model-select',
        'default-model-select',
        'param-model-select'
    ];

    selects.forEach(selectId => {
        const select = document.getElementById(selectId);
        if (select) {
            select.innerHTML = availableModelsData.map(m =>
                `<option value="${m.name}">${m.display_name}</option>`
            ).join('');
        }
    });

    // Display available models list in settings
    const availableModelsDiv = document.getElementById('available-models');
    if (availableModelsDiv) {
        availableModelsDiv.innerHTML = `
            <ul>
                ${availableModelsData.map(m => `<li>${m.display_name} (${m.name})</li>`).join('')}
            </ul>
        `;
    }

    // Auto-select first model in param-model-select and load its parameters
    const paramSelect = document.getElementById('param-model-select');
    if (paramSelect && availableModelsData.length > 0) {
        paramSelect.value = availableModelsData[0].name;
        // Trigger load parameters for the first model
        loadModelParameters();
    }
}

async function saveDefaultModel() {
    const modelName = document.getElementById('default-model-select').value;

    try {
        const response = await fetch(`/api/settings/models/default?model_name=${modelName}`, {
            method: 'PUT'
        });

        if (!response.ok) throw new Error('Failed to save default model');

        alert('デフォルトモデルを保存しました / Default model saved');

        // Update execution dropdowns
        document.getElementById('model-select').value = modelName;
        document.getElementById('batch-model-select').value = modelName;

    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

async function saveDefaultProject() {
    const projectId = document.getElementById('default-project-select').value;

    if (!projectId) {
        alert('プロジェクトを選択してください / Please select a project');
        return;
    }

    try {
        const response = await fetch(`/api/settings/default-project?project_id=${projectId}`, {
            method: 'PUT'
        });

        if (!response.ok) throw new Error('Failed to save default project');

        const data = await response.json();
        alert(`デフォルトプロジェクトを保存しました / Default project saved: ${data.project_name}`);

        // Update single execution dropdown
        const singleSelect = document.getElementById('single-project-select');
        if (singleSelect) {
            singleSelect.value = projectId;
            // Trigger project change to load prompts
            await onProjectChange();
        }

    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

async function loadModelParameters() {
    const modelName = document.getElementById('param-model-select').value;
    if (!modelName) return;

    try {
        const response = await fetch(`/api/settings/models/${modelName}/parameters`);
        currentModelParams = await response.json();

        // Show form
        document.getElementById('model-parameters-form').style.display = 'block';

        // Populate form with active parameters
        const active = currentModelParams.active_parameters;
        const defaults = currentModelParams.default_parameters;

        // Check model type
        const isGPT5 = modelName.includes('gpt-5') || modelName.includes('gpt5');
        const isAzureGPT5 = isGPT5 && modelName.includes('azure');
        const isOpenAIGPT5 = isGPT5 && modelName.includes('openai');

        // Get all parameter groups
        const temperatureGroup = document.getElementById('param-temperature-group');
        const maxTokensGroup = document.getElementById('param-max-tokens-group');
        const topPGroup = document.getElementById('param-top-p-group');
        const maxOutputTokensGroup = document.getElementById('param-max-output-tokens-group');
        const verbosityGroup = document.getElementById('param-verbosity-group');
        const reasoningEffortGroup = document.getElementById('param-reasoning-effort-group');

        if (isAzureGPT5) {
            // Azure GPT-5: Show max_output_tokens only
            temperatureGroup.style.display = 'none';
            maxTokensGroup.style.display = 'none';
            topPGroup.style.display = 'none';
            maxOutputTokensGroup.style.display = 'block';
            verbosityGroup.style.display = 'none';
            reasoningEffortGroup.style.display = 'none';

            // Set Azure GPT-5 parameter values
            document.getElementById('param-max-output-tokens').value = active.max_output_tokens || defaults.max_output_tokens || 8192;
            document.getElementById('default-max-output-tokens').textContent = `(デフォルト / Default: ${defaults.max_output_tokens || 8192})`;
        } else if (isOpenAIGPT5) {
            // OpenAI GPT-5: Show verbosity and reasoning_effort
            temperatureGroup.style.display = 'none';
            maxTokensGroup.style.display = 'none';
            topPGroup.style.display = 'none';
            maxOutputTokensGroup.style.display = 'none';
            verbosityGroup.style.display = 'block';
            reasoningEffortGroup.style.display = 'block';

            // Set OpenAI GPT-5 parameter values
            document.getElementById('param-verbosity').value = active.verbosity || defaults.verbosity || 'medium';
            document.getElementById('param-reasoning-effort').value = active.reasoning_effort || defaults.reasoning_effort || 'medium';

            document.getElementById('default-verbosity').textContent = `(デフォルト / Default: ${defaults.verbosity || 'medium'})`;
            document.getElementById('default-reasoning-effort').textContent = `(デフォルト / Default: ${defaults.reasoning_effort || 'medium'})`;
        } else {
            // Non-GPT-5: Show traditional parameters
            temperatureGroup.style.display = 'block';
            maxTokensGroup.style.display = 'block';
            topPGroup.style.display = 'block';
            maxOutputTokensGroup.style.display = 'none';
            verbosityGroup.style.display = 'none';
            reasoningEffortGroup.style.display = 'none';

            // Set traditional parameter values
            document.getElementById('param-temperature').value = active.temperature;
            document.getElementById('param-max-tokens').value = active.max_tokens;
            document.getElementById('param-top-p').value = active.top_p;

            document.getElementById('default-temperature').textContent = `(デフォルト / Default: ${defaults.temperature})`;
            document.getElementById('default-max-tokens').textContent = `(デフォルト / Default: ${defaults.max_tokens})`;
            document.getElementById('default-top-p').textContent = `(デフォルト / Default: ${defaults.top_p})`;
        }

    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

async function saveModelParameters() {
    const modelName = document.getElementById('param-model-select').value;
    const isGPT5 = modelName.includes('gpt-5') || modelName.includes('gpt5');
    const isAzureGPT5 = isGPT5 && modelName.includes('azure');
    const isOpenAIGPT5 = isGPT5 && modelName.includes('openai');

    let parameters;

    if (isAzureGPT5) {
        // Azure GPT-5: Send max_output_tokens only
        parameters = {
            max_output_tokens: parseInt(document.getElementById('param-max-output-tokens').value)
        };
    } else if (isOpenAIGPT5) {
        // OpenAI GPT-5: Send verbosity and reasoning_effort
        parameters = {
            verbosity: document.getElementById('param-verbosity').value,
            reasoning_effort: document.getElementById('param-reasoning-effort').value
        };
    } else {
        // Non-GPT-5: Send traditional parameters
        parameters = {
            temperature: parseFloat(document.getElementById('param-temperature').value),
            max_tokens: parseInt(document.getElementById('param-max-tokens').value),
            top_p: parseFloat(document.getElementById('param-top-p').value)
        };
    }

    try {
        const response = await fetch(`/api/settings/models/${modelName}/parameters`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({model_name: modelName, parameters})
        });

        if (!response.ok) throw new Error('Failed to save parameters');

        alert('パラメータを保存しました / Parameters saved');
        await loadModelParameters();

    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

async function resetModelParameters() {
    const modelName = document.getElementById('param-model-select').value;

    if (!confirm('パラメータをデフォルトに戻しますか？ / Reset parameters to defaults?')) return;

    try {
        const response = await fetch(`/api/settings/models/${modelName}/parameters`, {
            method: 'DELETE'
        });

        if (!response.ok) throw new Error('Failed to reset parameters');

        alert('パラメータをリセットしました / Parameters reset');
        await loadModelParameters();

    } catch (error) {
        alert(`エラー / Error: ${error.message}`);
    }
}

// ========================================
// Job Parallelism Settings
// ========================================

let currentSingleJobId = null;
let currentBatchJobId = null;

async function loadJobParallelism() {
    try {
        const response = await fetch('/api/settings/job-parallelism');
        if (!response.ok) throw new Error('Failed to load parallelism setting');

        const data = await response.json();
        document.getElementById('job-parallelism').value = data.parallelism;

    } catch (error) {
        console.error('Failed to load job parallelism:', error);
    }
}

async function saveJobParallelism() {
    const parallelism = parseInt(document.getElementById('job-parallelism').value);
    const statusEl = document.getElementById('parallelism-status');

    if (parallelism < 1 || parallelism > 99) {
        statusEl.textContent = 'エラー: 1-99の範囲で設定してください / Error: Must be 1-99';
        statusEl.style.color = '#e74c3c';
        return;
    }

    try {
        const response = await fetch(`/api/settings/job-parallelism?parallelism=${parallelism}`, {
            method: 'PUT'
        });

        if (!response.ok) throw new Error('Failed to save parallelism setting');

        const data = await response.json();
        statusEl.textContent = '保存しました / Saved';
        statusEl.style.color = '#27ae60';

        setTimeout(() => {
            statusEl.textContent = '';
        }, 2000);

    } catch (error) {
        statusEl.textContent = `エラー / Error: ${error.message}`;
        statusEl.style.color = '#e74c3c';
    }
}

// ========================================
// Text File Extensions Setting
// ========================================

async function loadTextFileExtensions() {
    try {
        const response = await fetch('/api/settings/text-file-extensions');
        if (!response.ok) throw new Error('Failed to load text file extensions');

        const data = await response.json();
        document.getElementById('text-file-extensions').value = data.extensions || '';

    } catch (error) {
        console.error('Failed to load text file extensions:', error);
    }
}

async function saveTextFileExtensions() {
    const extensions = document.getElementById('text-file-extensions').value;
    const statusEl = document.getElementById('text-extensions-status');

    try {
        const response = await fetch(`/api/settings/text-file-extensions?extensions=${encodeURIComponent(extensions)}`, {
            method: 'PUT'
        });

        if (!response.ok) throw new Error('Failed to save text file extensions');

        const data = await response.json();
        document.getElementById('text-file-extensions').value = data.extensions;

        statusEl.textContent = '保存しました / Saved';
        statusEl.style.color = '#27ae60';

        setTimeout(() => {
            statusEl.textContent = '';
        }, 2000);

    } catch (error) {
        statusEl.textContent = `エラー / Error: ${error.message}`;
        statusEl.style.color = '#e74c3c';
    }
}

async function resetTextFileExtensions() {
    const statusEl = document.getElementById('text-extensions-status');

    try {
        const response = await fetch('/api/settings/text-file-extensions', {
            method: 'DELETE'
        });

        if (!response.ok) throw new Error('Failed to reset text file extensions');

        const data = await response.json();
        document.getElementById('text-file-extensions').value = data.extensions;

        statusEl.textContent = 'デフォルトにリセットしました / Reset to default';
        statusEl.style.color = '#27ae60';

        setTimeout(() => {
            statusEl.textContent = '';
        }, 2000);

    } catch (error) {
        statusEl.textContent = `エラー / Error: ${error.message}`;
        statusEl.style.color = '#e74c3c';
    }
}

// ========================================
// Job Cancellation
// ========================================

/**
 * Delete/cancel a job from the history list (trash icon click)
 * @param {number} jobId - Job ID to delete
 * @param {string} jobType - 'single' or 'batch'
 */
async function deleteJob(jobId, jobType) {
    if (!confirm(`Job #${jobId} を削除しますか？\nDelete Job #${jobId}?`)) {
        return;
    }

    try {
        const response = await fetch(`/api/jobs/${jobId}/cancel`, {
            method: 'POST'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to delete job');
        }

        const data = await response.json();

        // Show success message
        showStatus(
            `Job #${jobId} を削除しました (${data.cancelled_count}件キャンセル) / Job #${jobId} deleted (${data.cancelled_count} items cancelled)`,
            'success'
        );

        // Reload the appropriate history
        if (jobType === 'single') {
            await loadConfig();  // Reloads single job history
        } else if (jobType === 'batch') {
            const projectSelect = document.getElementById('batch-project-select');
            if (projectSelect && projectSelect.value) {
                const parsed = parseSelectValue(projectSelect.value);
                if (parsed && parsed.id) {
                    await loadBatchJobHistory(parsed.id);
                }
            }
        }

    } catch (error) {
        console.error('Error deleting job:', error);
        showStatus(`削除エラー / Delete Error: ${error.message}`, 'error');
    }
}

async function cancelJob(jobId, buttonId, statusId) {
    if (!jobId) {
        alert('ジョブが実行されていません / No job is running');
        return;
    }

    try {
        const response = await fetch(`/api/jobs/${jobId}/cancel`, {
            method: 'POST'
        });

        if (!response.ok) throw new Error('Failed to cancel job');

        const data = await response.json();

        // Hide stop button
        document.getElementById(buttonId).style.display = 'none';

        // Show status message
        const statusEl = document.getElementById(statusId);
        if (statusEl) {
            statusEl.textContent = `停止しました: ${data.cancelled_count}件のアイテムをキャンセル / Stopped: ${data.cancelled_count} items cancelled`;
            statusEl.className = 'status-message status-info';
        }

    } catch (error) {
        alert(`停止エラー / Cancellation Error: ${error.message}`);
    }
}

async function cancelSingleJob() {
    // Stop polling first
    if (singlePollIntervalId) {
        clearInterval(singlePollIntervalId);
        singlePollIntervalId = null;
    }

    const jobId = currentSingleJobId;
    await cancelJob(currentSingleJobId, 'btn-stop-single', 'execution-status');
    hideSingleStopButton();

    // Reload job state and history after cancellation
    if (jobId && currentProjectId) {
        try {
            // Fetch updated job data
            const response = await fetch(`/api/projects/${currentProjectId}/jobs`);
            const allJobs = await response.json();
            const job = allJobs.find(j => j.id === jobId);

            if (job) {
                // Display final job state
                displayJobResults(job);
            }

            // Reload history
            await loadConfig();
        } catch (error) {
            console.error('Error reloading job after cancel:', error);
        }
    }
}

async function cancelBatchJob() {
    // Stop polling first
    if (batchPollIntervalId) {
        clearInterval(batchPollIntervalId);
        batchPollIntervalId = null;
    }

    const jobId = currentBatchJobId;
    const selectValue = document.getElementById('batch-project-select')?.value;
    const parsed = parseSelectValue(selectValue);
    const projectId = parsed?.id;

    // Use dedicated status element instead of batch-results-area to avoid overwriting results
    await cancelJob(currentBatchJobId, 'btn-stop-batch', 'batch-execution-status');
    hideBatchStopButton();

    // Show the status element
    const statusEl = document.getElementById('batch-execution-status');
    if (statusEl) {
        statusEl.style.display = 'block';
    }

    // Reload job state and history after cancellation
    if (jobId && projectId) {
        try {
            // Fetch updated job data
            const response = await fetch(`/api/projects/${projectId}/jobs`);
            const allJobs = await response.json();
            const job = allJobs.find(j => j.id === parseInt(jobId));

            if (job) {
                // Display final job state
                displayBatchResult(job);
            }

            // Reload batch job history
            await loadBatchJobHistory(projectId);
        } catch (error) {
            console.error('Error reloading job after cancel:', error);
        }
    }
}

/**
 * Show JSON to CSV template converter modal
 * Allows user to paste JSON sample and generate parser config automatically
 */
function showJsonToCsvConverter() {
    const converterContent = `
        <div class="modal-header" style="display: flex; justify-content: space-between; align-items: center;">
            <span>📊 JSON → CSV テンプレート変換 / JSON to CSV Template Converter</span>
            <button class="btn btn-secondary" onclick="closeModal2()" style="margin: 0;">閉じる / Close</button>
        </div>
        <div class="modal-body" style="max-height: 70vh; overflow-y: auto;">
            <div class="form-group">
                <label style="font-weight: bold;">1. サンプルJSONを貼り付け / Paste Sample JSON:</label>
                <textarea id="json-sample-input" rows="15" style="font-family: 'Courier New', monospace; width: 100%;" placeholder='{
  "field1": { "score": 1, "reason": "理由" },
  "field2": { "nested": { "value": "test" } }
}'></textarea>
                <small style="color: #7f8c8d;">
                    LLMからの期待されるJSON出力形式を貼り付けてください。<br>
                    Paste the expected JSON output format from the LLM.
                </small>
            </div>
            <div class="form-group" style="margin-top: 1rem;">
                <button class="btn btn-primary" onclick="convertJsonToCsvTemplate()" style="width: 100%;">
                    🔄 変換 / Convert
                </button>
            </div>
            <div class="form-group" style="margin-top: 1rem;">
                <label style="font-weight: bold;">2. 生成されたパーサー設定 / Generated Parser Config:</label>
                <textarea id="generated-parser-config" rows="15" style="font-family: 'Courier New', monospace; width: 100%;" readonly placeholder="変換後のパーサー設定がここに表示されます / Generated parser config will appear here"></textarea>
            </div>
            <div class="form-group" style="margin-top: 1rem;">
                <label style="font-weight: bold;">3. CSVヘッダープレビュー / CSV Header Preview:</label>
                <textarea id="csv-header-preview" rows="3" style="font-family: 'Courier New', monospace; width: 100%; background: #f8f9fa;" readonly placeholder="CSVヘッダーがここに表示されます / CSV header will appear here"></textarea>
            </div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeModal2()">閉じる / Close</button>
            <button class="btn btn-primary" onclick="applyGeneratedParserConfig()" style="background-color: #27ae60;">
                ✅ パーサー設定に適用 / Apply to Parser Config
            </button>
        </div>
    `;
    showModal2(converterContent);
}

/**
 * Convert JSON sample to CSV template parser config
 * Recursively extracts all leaf paths from the JSON structure
 */
function convertJsonToCsvTemplate() {
    const jsonInput = document.getElementById('json-sample-input').value.trim();
    const outputArea = document.getElementById('generated-parser-config');
    const headerPreview = document.getElementById('csv-header-preview');

    if (!jsonInput) {
        alert('JSONを入力してください / Please enter JSON');
        return;
    }

    try {
        // Remove <...> placeholders and replace with sample values for parsing
        let cleanedJson = jsonInput
            // Handle "<...>" (quoted placeholder) -> "sample"
            .replace(/"<[^>]+>"/g, '"sample"')
            // Handle <...> (unquoted placeholder) -> "sample"
            .replace(/<[^>]+>/g, '"sample"')
            // Fix trailing commas
            .replace(/,\s*}/g, '}')
            .replace(/,\s*]/g, ']');

        const jsonData = JSON.parse(cleanedJson);

        // Extract all leaf paths
        const paths = {};
        const fieldNames = [];
        extractPaths(jsonData, '$', paths, fieldNames);

        // Generate CSV template
        const csvTemplate = fieldNames.map(name => '$' + name + '$').join(',');

        // Generate parser config
        const parserConfig = {
            type: 'json_path',
            paths: paths,
            csv_template: csvTemplate
        };

        outputArea.value = JSON.stringify(parserConfig, null, 2);
        headerPreview.value = fieldNames.join(',');

    } catch (error) {
        alert('JSONの解析に失敗しました / Failed to parse JSON: ' + error.message);
        outputArea.value = 'Error: ' + error.message;
        headerPreview.value = '';
    }
}

/**
 * Recursively extract paths from JSON object
 * @param {any} obj - Current object/value
 * @param {string} currentPath - Current JSON path (e.g., "$.field")
 * @param {object} paths - Output object for path mappings
 * @param {array} fieldNames - Output array for field names (in order)
 */
function extractPaths(obj, currentPath, paths, fieldNames) {
    if (obj === null || obj === undefined) {
        return;
    }

    if (typeof obj === 'object' && !Array.isArray(obj)) {
        // Object: recurse into properties
        for (const key of Object.keys(obj)) {
            const newPath = currentPath === '$' ? '$.' + key : currentPath + '.' + key;
            extractPaths(obj[key], newPath, paths, fieldNames);
        }
    } else if (Array.isArray(obj)) {
        // Array: skip arrays for now (complex to handle in CSV)
        // Could be extended to handle arrays if needed
    } else {
        // Leaf value (string, number, boolean)
        // Generate field name from path (replace dots with underscores)
        const fieldName = currentPath.replace(/^\$\./, '').replace(/\./g, '_');
        paths[fieldName] = currentPath;
        fieldNames.push(fieldName);
    }
}

/**
 * Apply generated parser config to the main parser config textarea
 */
function applyGeneratedParserConfig() {
    const generatedConfig = document.getElementById('generated-parser-config').value;

    if (!generatedConfig || generatedConfig.startsWith('Error:')) {
        alert('有効なパーサー設定がありません / No valid parser config available');
        return;
    }

    try {
        // Validate JSON
        const config = JSON.parse(generatedConfig);

        // Apply to main parser config
        const mainConfigArea = document.getElementById('edit-parser-config');
        const parserTypeSelect = document.getElementById('edit-parser-type');

        if (mainConfigArea && parserTypeSelect) {
            mainConfigArea.value = generatedConfig;
            parserTypeSelect.value = config.type || 'json_path';
        }

        closeModal2();
        alert('パーサー設定に適用しました。保存ボタンで保存してください。\n\nApplied to parser config. Click Save to save.');

    } catch (error) {
        alert('パーサー設定の適用に失敗しました / Failed to apply parser config: ' + error.message);
    }
}

// ========================================
// Workflow Functions (v2.0)
// ========================================

/**
 * Global HTML escape function for workflow code
 */
function escapeHtmlGlobal(unsafe) {
    if (unsafe === null || unsafe === undefined) return '';
    return String(unsafe)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

/** Global state for workflows */
let workflows = [];
let selectedWorkflow = null;
let workflowStepCounter = 0;
let selectedWorkflowProjectId = null;

/**
 * Initialize workflow tab - populate project selector
 */
async function initWorkflowTab() {
    try {
        // Load projects if not already loaded
        if (!allProjects || allProjects.length === 0) {
            await loadProjects();
        }

        const select = document.getElementById('workflow-project-select');
        if (!select) return;

        // Populate project options
        select.innerHTML = '<option value="">-- プロジェクトを選択 / Select Project --</option>' +
            allProjects.map(p => `<option value="${p.id}">${escapeHtmlGlobal(p.name)}</option>`).join('');

        // Clear workflow list until project is selected
        const list = document.getElementById('workflow-list');
        if (list) {
            list.innerHTML = '<div class="empty-message">プロジェクトを選択してください<br>Please select a project</div>';
        }
    } catch (error) {
        console.error('Error initializing workflow tab:', error);
    }
}

/**
 * Handle workflow project selection change
 */
async function onWorkflowProjectChange() {
    const select = document.getElementById('workflow-project-select');
    const createBtn = document.getElementById('btn-create-workflow');
    const hint = document.getElementById('workflow-project-hint');

    selectedWorkflowProjectId = select.value ? parseInt(select.value) : null;
    console.log('[onWorkflowProjectChange] selectedWorkflowProjectId:', selectedWorkflowProjectId);

    if (selectedWorkflowProjectId) {
        createBtn.disabled = false;
        if (hint) hint.style.display = 'none';
        console.log('[onWorkflowProjectChange] Calling loadWorkflows()');
        await loadWorkflows();
    } else {
        createBtn.disabled = true;
        if (hint) hint.style.display = '';
        const list = document.getElementById('workflow-list');
        if (list) {
            list.innerHTML = '<div class="empty-message">プロジェクトを選択してください<br>Please select a project</div>';
        }
    }

    // Hide any open editors
    hideWorkflowEditor();
}

/**
 * Load and display workflow list (filtered by selected project)
 */
async function loadWorkflows() {
    try {
        // Build URL with project filter
        let url = '/api/workflows';
        if (selectedWorkflowProjectId) {
            url += `?project_id=${selectedWorkflowProjectId}`;
        }
        console.log('[loadWorkflows] Fetching from:', url, 'selectedWorkflowProjectId:', selectedWorkflowProjectId);

        const response = await fetch(url);
        if (!response.ok) throw new Error('Failed to load workflows');
        workflows = await response.json();
        console.log('[loadWorkflows] Received workflows:', workflows.length, workflows.map(w => ({id: w.id, name: w.name, project_id: w.project_id})));

        const list = document.getElementById('workflow-list');
        if (!list) {
            console.error('[loadWorkflows] workflow-list element not found!');
            return;
        }

        if (workflows.length === 0) {
            list.innerHTML = '<div class="empty-message">ワークフローがありません<br>No workflows yet</div>';
            return;
        }

        list.innerHTML = workflows.map(w => `
            <div class="workflow-item ${selectedWorkflow && selectedWorkflow.id === w.id ? 'selected' : ''}"
                 onclick="selectWorkflow(${w.id})">
                <div class="workflow-name">${escapeHtmlGlobal(w.name)}</div>
                <div class="workflow-info">${w.steps.length} ステップ / steps</div>
            </div>
        `).join('');
        console.log('[loadWorkflows] Rendered', workflows.length, 'workflow items');

    } catch (error) {
        console.error('Error loading workflows:', error);
    }
}

/**
 * Show workflow editor for creating new workflow
 */
function showCreateWorkflowForm() {
    selectedWorkflow = null;
    workflowStepCounter = 0;

    document.getElementById('workflow-editor-title').textContent = 'ワークフロー作成 / Create Workflow';
    document.getElementById('workflow-id').value = '';
    document.getElementById('workflow-name').value = '';
    document.getElementById('workflow-description').value = '';
    document.getElementById('workflow-steps-container').innerHTML = '';

    document.getElementById('workflow-editor').style.display = 'block';

    // Deselect in list
    document.querySelectorAll('.workflow-item').forEach(el => el.classList.remove('selected'));
}

/**
 * Hide workflow editor
 */
function hideWorkflowEditor() {
    document.getElementById('workflow-editor').style.display = 'none';
}

/**
 * Add a step to the workflow form
 */
async function addWorkflowStep(stepData = null) {
    workflowStepCounter++;
    const stepNumber = workflowStepCounter;

    // Load projects for dropdown if not already loaded
    if (!allProjects || allProjects.length === 0) {
        await loadProjects();
    }

    const container = document.getElementById('workflow-steps-container');
    const stepDiv = document.createElement('div');
    stepDiv.className = 'workflow-step';
    stepDiv.id = `workflow-step-${stepNumber}`;
    stepDiv.dataset.stepId = stepData ? stepData.id : '';

    const projectOptions = allProjects.map(p =>
        `<option value="${p.id}" ${stepData && stepData.project_id === p.id ? 'selected' : ''}>${escapeHtmlGlobal(p.name)}</option>`
    ).join('');

    stepDiv.innerHTML = `
        <div class="step-header">
            <span class="step-number">Step ${stepNumber}</span>
            <div class="step-controls">
                <button type="button" class="btn btn-move btn-sm" onclick="moveWorkflowStepUp(this)" title="上に移動 / Move up">▲</button>
                <button type="button" class="btn btn-move btn-sm" onclick="moveWorkflowStepDown(this)" title="下に移動 / Move down">▼</button>
                <button type="button" class="btn btn-danger btn-sm" onclick="removeWorkflowStep(this)" title="削除 / Remove">✕</button>
            </div>
        </div>
        <div class="form-group">
            <label>ステップ名 / Step Name:</label>
            <input type="text" class="step-name" value="${stepData ? escapeHtmlGlobal(stepData.step_name) : 'step' + stepNumber}"
                   placeholder="step1, summarize, etc.">
        </div>
        <div class="form-group">
            <label>プロジェクト / Project:</label>
            <select class="step-project" onchange="onStepProjectChange(${stepNumber}, this.value)">
                <option value="">-- 選択 / Select --</option>
                ${projectOptions}
            </select>
        </div>
        <div class="form-group">
            <label>プロンプト / Prompt:</label>
            <div style="display: flex; gap: 0.5rem; align-items: center;">
                <select class="step-prompt" id="step-prompt-${stepNumber}" style="flex: 1;">
                    <option value="">-- プロジェクトを先に選択 / Select project first --</option>
                </select>
                <button type="button" class="btn btn-secondary btn-sm" id="step-prompt-edit-${stepNumber}"
                        onclick="openPromptEditorForStep(${stepNumber})"
                        title="プロンプトを確認・編集 / Preview/Edit Prompt" disabled>
                    📝 確認
                </button>
            </div>
        </div>
        <div class="form-group">
            <label>
                入力マッピング / Input Mapping (JSON):
                <button type="button" class="btn-var-picker" onclick="openVariablePickerForStep(${stepNumber})" title="変数を挿入 / Insert variable">
                    🔧 変数
                </button>
            </label>
            <textarea class="step-input-mapping" id="step-input-mapping-${stepNumber}" rows="3" placeholder='{"param": "{{step1.field}}"}'>${stepData && stepData.input_mapping ? JSON.stringify(stepData.input_mapping, null, 2) : ''}</textarea>
            <small style="color: #7f8c8d;">
                {{input.param}} = 初期入力 / initial input<br>
                {{step1.field}} = 前ステップの出力 / previous step output
            </small>
        </div>
    `;

    container.appendChild(stepDiv);

    // If editing an existing step with project_id, load prompts
    if (stepData && stepData.project_id) {
        await loadPromptsForWorkflowStep(stepNumber, stepData.project_id, stepData.prompt_id);
    }
}

/**
 * Handle project change in workflow step - load prompts for the selected project
 */
async function onStepProjectChange(stepNumber, projectId) {
    const promptSelect = document.getElementById(`step-prompt-${stepNumber}`);
    if (!promptSelect) return;

    if (!projectId) {
        promptSelect.innerHTML = '<option value="">-- プロジェクトを先に選択 / Select project first --</option>';
        return;
    }

    await loadPromptsForWorkflowStep(stepNumber, projectId, null);
}

/**
 * Load prompts for a workflow step's project
 */
async function loadPromptsForWorkflowStep(stepNumber, projectId, selectedPromptId) {
    const promptSelect = document.getElementById(`step-prompt-${stepNumber}`);
    const editBtn = document.getElementById(`step-prompt-edit-${stepNumber}`);
    if (!promptSelect) return;

    promptSelect.innerHTML = '<option value="">読み込み中... / Loading...</option>';
    if (editBtn) editBtn.disabled = true;

    try {
        const response = await fetch(`/api/projects/${projectId}/prompts`);
        if (!response.ok) throw new Error('Failed to load prompts');

        const prompts = await response.json();

        let options = '<option value="">-- プロンプトを選択 / Select prompt --</option>';
        prompts.forEach(p => {
            const selected = selectedPromptId && p.id === selectedPromptId ? 'selected' : '';
            options += `<option value="${p.id}" ${selected}>${escapeHtmlGlobal(p.name)}</option>`;
        });

        promptSelect.innerHTML = options;

        // Add onchange handler to enable/disable edit button
        promptSelect.onchange = () => {
            if (editBtn) {
                editBtn.disabled = !promptSelect.value;
            }
        };

        // Enable edit button if a prompt is already selected
        if (selectedPromptId && editBtn) {
            editBtn.disabled = false;
        }
    } catch (error) {
        console.error('Error loading prompts for step:', error);
        promptSelect.innerHTML = '<option value="">エラー / Error</option>';
    }
}

/**
 * Remove a step from the workflow form
 */
function removeWorkflowStep(buttonEl) {
    const stepDiv = buttonEl.closest('.workflow-step');
    if (stepDiv) {
        stepDiv.remove();
        renumberWorkflowSteps();
    }
}

/**
 * Move a workflow step up (swap with previous sibling)
 */
function moveWorkflowStepUp(buttonEl) {
    const stepDiv = buttonEl.closest('.workflow-step');
    if (!stepDiv) return;

    const prevStep = stepDiv.previousElementSibling;
    if (prevStep && prevStep.classList.contains('workflow-step')) {
        stepDiv.parentNode.insertBefore(stepDiv, prevStep);
        renumberWorkflowSteps();
    }
}

/**
 * Move a workflow step down (swap with next sibling)
 */
function moveWorkflowStepDown(buttonEl) {
    const stepDiv = buttonEl.closest('.workflow-step');
    if (!stepDiv) return;

    const nextStep = stepDiv.nextElementSibling;
    if (nextStep && nextStep.classList.contains('workflow-step')) {
        stepDiv.parentNode.insertBefore(nextStep, stepDiv);
        renumberWorkflowSteps();
    }
}

/**
 * Renumber all workflow steps after reordering
 */
function renumberWorkflowSteps() {
    const container = document.getElementById('workflow-steps-container');
    const steps = container.querySelectorAll('.workflow-step');

    steps.forEach((step, index) => {
        const stepNumber = index + 1;
        // Update step number display
        const stepNumberEl = step.querySelector('.step-number');
        if (stepNumberEl) {
            stepNumberEl.textContent = `Step ${stepNumber}`;
        }
    });
}

/**
 * Save workflow (create or update)
 */
async function saveWorkflow() {
    const workflowId = document.getElementById('workflow-id').value;
    const name = document.getElementById('workflow-name').value.trim();
    const description = document.getElementById('workflow-description').value.trim();

    if (!name) {
        alert('ワークフロー名を入力してください / Please enter workflow name');
        return;
    }

    // Collect steps
    const stepDivs = document.querySelectorAll('.workflow-step');
    const steps = [];
    let stepOrder = 0;

    for (const stepDiv of stepDivs) {
        stepOrder++;
        const stepName = stepDiv.querySelector('.step-name').value.trim();
        const projectId = stepDiv.querySelector('.step-project').value;
        const promptSelect = stepDiv.querySelector('.step-prompt');
        const promptId = promptSelect ? promptSelect.value : '';
        const inputMappingStr = stepDiv.querySelector('.step-input-mapping').value.trim();

        if (!stepName || !projectId) {
            alert(`Step ${stepOrder}: ステップ名とプロジェクトは必須です / Step name and project are required`);
            return;
        }

        let inputMapping = null;
        if (inputMappingStr) {
            try {
                inputMapping = JSON.parse(inputMappingStr);
            } catch (e) {
                alert(`Step ${stepOrder}: 入力マッピングのJSONが不正です / Invalid input mapping JSON`);
                return;
            }
        }

        const stepData = {
            step_name: stepName,
            project_id: parseInt(projectId),
            step_order: stepOrder,
            input_mapping: inputMapping,
            execution_mode: 'sequential'
        };

        // Include prompt_id if selected
        if (promptId) {
            stepData.prompt_id = parseInt(promptId);
        }

        steps.push(stepData);
    }

    try {
        let response;
        if (workflowId) {
            // Update existing workflow
            response = await fetch(`/api/workflows/${workflowId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, description })
            });

            if (!response.ok) throw new Error('Failed to update workflow');

            // Update steps: delete all and re-add
            const existingWorkflow = await response.json();
            for (const step of existingWorkflow.steps) {
                await fetch(`/api/workflows/${workflowId}/steps/${step.id}`, { method: 'DELETE' });
            }
            for (const step of steps) {
                await fetch(`/api/workflows/${workflowId}/steps`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(step)
                });
            }
        } else {
            // Create new workflow (include project_id)
            response = await fetch('/api/workflows', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name,
                    description,
                    project_id: selectedWorkflowProjectId,
                    steps
                })
            });

            if (!response.ok) throw new Error('Failed to create workflow');
        }

        await loadWorkflows();
        hideWorkflowEditor();

    } catch (error) {
        console.error('Error saving workflow:', error);
        alert('ワークフローの保存に失敗しました / Failed to save workflow: ' + error.message);
    }
}

/**
 * Select and display a workflow
 */
async function selectWorkflow(workflowId) {
    try {
        const response = await fetch(`/api/workflows/${workflowId}`);
        if (!response.ok) throw new Error('Failed to load workflow');
        selectedWorkflow = await response.json();

        // Update list selection
        document.querySelectorAll('.workflow-item').forEach(el => el.classList.remove('selected'));
        const selectedItem = document.querySelector(`.workflow-item[onclick="selectWorkflow(${workflowId})"]`);
        if (selectedItem) selectedItem.classList.add('selected');

        // Show editor with workflow data
        document.getElementById('workflow-editor-title').textContent = 'ワークフロー編集 / Edit Workflow';
        document.getElementById('workflow-id').value = selectedWorkflow.id;
        document.getElementById('workflow-name').value = selectedWorkflow.name;
        document.getElementById('workflow-description').value = selectedWorkflow.description || '';

        // Clear and rebuild steps
        document.getElementById('workflow-steps-container').innerHTML = '';
        workflowStepCounter = 0;

        for (const step of selectedWorkflow.steps) {
            await addWorkflowStep(step);
        }

        document.getElementById('workflow-editor').style.display = 'block';

    } catch (error) {
        console.error('Error selecting workflow:', error);
        alert('ワークフローの読み込みに失敗しました / Failed to load workflow');
    }
}

/**
 * Delete selected workflow
 */
async function deleteWorkflow() {
    if (!selectedWorkflow) {
        alert('ワークフローを選択してください / Please select a workflow');
        return;
    }

    if (!confirm(`"${selectedWorkflow.name}" を削除しますか？\nDelete "${selectedWorkflow.name}"?`)) {
        return;
    }

    try {
        const response = await fetch(`/api/workflows/${selectedWorkflow.id}`, { method: 'DELETE' });
        if (!response.ok) throw new Error('Failed to delete workflow');

        selectedWorkflow = null;
        hideWorkflowEditor();
        await loadWorkflows();

    } catch (error) {
        console.error('Error deleting workflow:', error);
        alert('ワークフローの削除に失敗しました / Failed to delete workflow');
    }
}

// ========== Variable Picker for Workflow Steps ==========

let variablePickerTarget = null;  // The textarea that will receive the inserted variable
let cachedWorkflowVariables = null;  // Cached variables data
let variablePickerCurrentStep = null;  // Current step number for variable filtering

/**
 * Open the variable picker dialog
 * @param {HTMLElement} targetTextarea - The textarea to insert the variable into
 * @param {number} stepNumber - Optional step number for filtering (workflow context)
 */
async function openVariablePicker(targetTextarea, stepNumber = null) {
    variablePickerTarget = targetTextarea;
    variablePickerCurrentStep = stepNumber;

    // Show the modal
    document.getElementById('variable-picker-overlay').classList.add('active');

    // Clear search
    document.getElementById('variable-search').value = '';

    // Load variables with context-aware filtering
    await loadWorkflowVariablesWithContext(stepNumber);
}

/**
 * Close the variable picker dialog
 */
function closeVariablePicker() {
    document.getElementById('variable-picker-overlay').classList.remove('active');
    variablePickerTarget = null;
}

/**
 * Load workflow variables from API and render them (legacy function)
 */
async function loadWorkflowVariables() {
    await loadWorkflowVariablesWithContext(null);
}

/**
 * Load workflow variables with context-aware filtering for workflow steps
 * @param {number} stepNumber - Current step number (for filtering previous steps)
 */
async function loadWorkflowVariablesWithContext(stepNumber) {
    const container = document.getElementById('variable-categories');

    try {
        // Fetch variables if not cached
        if (!cachedWorkflowVariables) {
            const response = await fetch('/api/workflow-variables');
            if (!response.ok) throw new Error('Failed to load variables');
            cachedWorkflowVariables = await response.json();
        }

        // Get current workflow steps for context-aware filtering
        const workflowSteps = getCurrentWorkflowSteps();

        // Build dynamic categories based on workflow context
        const filteredCategories = buildFilteredCategories(stepNumber, workflowSteps);

        renderVariableCategories(filteredCategories, '');
    } catch (error) {
        console.error('Error loading workflow variables:', error);
        container.innerHTML = `<p style="padding: 1rem; color: #e74c3c;">変数の読み込みに失敗しました / Failed to load variables</p>`;
    }
}

/**
 * Get current workflow steps from the editor form
 * @returns {Array} Array of step info objects {stepName, projectId, promptId, promptName}
 */
function getCurrentWorkflowSteps() {
    const steps = [];
    const stepDivs = document.querySelectorAll('.workflow-step');

    stepDivs.forEach((stepDiv, index) => {
        const stepNumber = index + 1;
        const stepNameInput = stepDiv.querySelector('.step-name');
        const projectSelect = stepDiv.querySelector('.step-project');
        const promptSelect = stepDiv.querySelector('.step-prompt');

        steps.push({
            stepNumber: stepNumber,
            stepName: stepNameInput ? stepNameInput.value.trim() : `step${stepNumber}`,
            projectId: projectSelect ? parseInt(projectSelect.value) || null : null,
            promptId: promptSelect ? parseInt(promptSelect.value) || null : null,
            promptName: promptSelect && promptSelect.selectedIndex >= 0
                ? promptSelect.options[promptSelect.selectedIndex].text
                : ''
        });
    });

    return steps;
}

/**
 * Build filtered variable categories based on workflow context
 * @param {number} currentStepNumber - The step number being edited
 * @param {Array} workflowSteps - Array of all workflow steps
 * @returns {Array} Filtered categories for the variable picker
 */
function buildFilteredCategories(currentStepNumber, workflowSteps) {
    const categories = [];

    // Category 1: Initial Input (always available)
    const inputVars = [
        {
            name: "(入力パラメータ名)",
            variable: "{{input.パラメータ名}}",
            type: "input",
            source: "ワークフロー初期入力"
        }
    ];

    // Add input params from the selected project's prompts
    const selectedProjectId = getWorkflowSelectedProjectId();
    if (selectedProjectId && cachedWorkflowVariables) {
        for (const cat of cachedWorkflowVariables.categories) {
            if (cat.category_id.startsWith('prompt_') && cat.category_id.endsWith('_input')) {
                for (const v of cat.variables) {
                    // Only add if the prompt belongs to the selected project or related
                    inputVars.push({
                        name: v.name,
                        variable: v.variable,
                        type: "input",
                        source: v.source
                    });
                }
            }
        }
    }

    categories.push({
        category_id: "input",
        category_name: "📥 初期入力 / Initial Input",
        variables: inputVars
    });

    // Category 2+: Previous steps' outputs (for steps before currentStepNumber)
    if (currentStepNumber && workflowSteps.length > 0) {
        for (const step of workflowSteps) {
            // Only show steps before the current one
            if (step.stepNumber >= currentStepNumber) continue;
            if (!step.promptId) continue;

            const stepVars = [];

            // Get output fields from cached variables for this prompt
            if (cachedWorkflowVariables) {
                for (const cat of cachedWorkflowVariables.categories) {
                    if (cat.category_id === `prompt_${step.promptId}`) {
                        for (const v of cat.variables) {
                            // Replace placeholder step name with actual step name
                            const actualVar = v.variable.replace('ステップ名', step.stepName);
                            stepVars.push({
                                name: v.name,
                                variable: actualVar,
                                type: "output",
                                source: `${step.promptName || v.source}`
                            });
                        }
                    }
                }
            }

            // Add raw_response for this step
            stepVars.push({
                name: "raw_response",
                variable: `{{${step.stepName}.raw_response}}`,
                type: "output",
                source: "生のLLM出力"
            });

            if (stepVars.length > 0) {
                categories.push({
                    category_id: `step_${step.stepNumber}`,
                    category_name: `📤 Step ${step.stepNumber}: ${step.stepName} の出力`,
                    variables: stepVars
                });
            }
        }
    }

    // Also add global output variables if no workflow context
    if (!currentStepNumber && cachedWorkflowVariables) {
        for (const cat of cachedWorkflowVariables.categories) {
            if (!cat.category_id.endsWith('_input') && cat.category_id !== 'input') {
                categories.push(cat);
            }
        }
    }

    return categories;
}

/**
 * Get the selected project ID for the workflow context
 * @returns {number|null} The selected project ID or null
 */
function getWorkflowSelectedProjectId() {
    const projectSelect = document.getElementById('workflow-project-select');
    return projectSelect ? parseInt(projectSelect.value) || null : null;
}

/**
 * Render variable categories with optional filtering
 * @param {Array} categories - Array of category objects
 * @param {string} searchQuery - Search query to filter by
 */
function renderVariableCategories(categories, searchQuery) {
    const container = document.getElementById('variable-categories');
    const query = searchQuery.toLowerCase().trim();

    let html = '';
    let hasResults = false;

    for (const category of categories) {
        // Filter variables by search query
        const filteredVars = category.variables.filter(v =>
            !query ||
            v.name.toLowerCase().includes(query) ||
            v.variable.toLowerCase().includes(query) ||
            v.source.toLowerCase().includes(query)
        );

        if (filteredVars.length === 0) continue;
        hasResults = true;

        html += `
            <div class="variable-category" data-category="${escapeHtmlGlobal(category.category_id)}">
                <div class="variable-category-header" onclick="toggleVariableCategory(this)">
                    <span class="toggle-icon">▼</span>
                    <span>${escapeHtmlGlobal(category.category_name)}</span>
                    <span style="margin-left: auto; font-size: 0.75rem; color: #9e9e9e;">(${filteredVars.length})</span>
                </div>
                <ul class="variable-list">
        `;

        for (const varInfo of filteredVars) {
            html += `
                <li class="variable-item" onclick="insertVariable('${escapeHtmlGlobal(varInfo.variable)}')">
                    <span class="var-name">${escapeHtmlGlobal(varInfo.name)}</span>
                    <span class="var-syntax">${escapeHtmlGlobal(varInfo.variable)}</span>
                    <span class="var-source">${escapeHtmlGlobal(varInfo.source)}</span>
                </li>
            `;
        }

        html += `
                </ul>
            </div>
        `;
    }

    if (!hasResults) {
        html = `<div class="variable-no-results">検索結果がありません / No results found</div>`;
    }

    container.innerHTML = html;
}

/**
 * Toggle category collapsed state
 * @param {HTMLElement} headerElement - The clicked header element
 */
function toggleVariableCategory(headerElement) {
    const categoryDiv = headerElement.closest('.variable-category');
    categoryDiv.classList.toggle('collapsed');
}

/**
 * Filter variables based on search query
 * @param {string} query - Search query
 */
function filterVariables(query) {
    if (cachedWorkflowVariables) {
        renderVariableCategories(cachedWorkflowVariables.categories, query);
    }
}

/**
 * Insert a variable at the cursor position in the target textarea
 * @param {string} variable - The variable syntax to insert (e.g., "{{step1.answer}}")
 */
function insertVariable(variable) {
    if (!variablePickerTarget) {
        console.error('No target textarea for variable insertion');
        closeVariablePicker();
        return;
    }

    const textarea = variablePickerTarget;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const text = textarea.value;

    // Insert variable at cursor position
    textarea.value = text.substring(0, start) + variable + text.substring(end);

    // Move cursor after inserted variable
    const newPos = start + variable.length;
    textarea.selectionStart = newPos;
    textarea.selectionEnd = newPos;

    // Focus back on textarea
    textarea.focus();

    // Close the picker
    closeVariablePicker();

    // Trigger input event for any listeners
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
}

/**
 * Refresh cached workflow variables (call when prompts/parsers change)
 */
function refreshWorkflowVariables() {
    cachedWorkflowVariables = null;
}

/**
 * Open variable picker for a specific workflow step's input mapping textarea
 * @param {number} stepNumber - The step number
 */
function openVariablePickerForStep(stepNumber) {
    const textarea = document.getElementById(`step-input-mapping-${stepNumber}`);
    if (textarea) {
        // Find actual step position in the DOM (accounting for reordering)
        const stepDiv = textarea.closest('.workflow-step');
        let actualStepPosition = stepNumber;
        if (stepDiv) {
            const allSteps = document.querySelectorAll('.workflow-step');
            actualStepPosition = Array.from(allSteps).indexOf(stepDiv) + 1;
        }
        openVariablePicker(textarea, actualStepPosition);
    } else {
        console.error(`Textarea for step ${stepNumber} not found`);
    }
}

// Close variable picker when clicking overlay background
document.addEventListener('DOMContentLoaded', () => {
    const overlay = document.getElementById('variable-picker-overlay');
    if (overlay) {
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                closeVariablePicker();
            }
        });
    }

    // Initialize draggable window
    initDraggableWindow('prompt-editor-window', 'prompt-editor-header');
});


// ========== Draggable Prompt Editor Window ==========

let promptEditorDragState = {
    isDragging: false,
    startX: 0,
    startY: 0,
    startLeft: 0,
    startTop: 0
};

/**
 * Initialize draggable functionality for a window
 * @param {string} windowId - The window element ID
 * @param {string} headerId - The header element ID (drag handle)
 */
function initDraggableWindow(windowId, headerId) {
    const windowEl = document.getElementById(windowId);
    const headerEl = document.getElementById(headerId);

    if (!windowEl || !headerEl) return;

    headerEl.addEventListener('mousedown', (e) => {
        if (e.target.tagName === 'BUTTON') return;

        promptEditorDragState.isDragging = true;
        promptEditorDragState.startX = e.clientX;
        promptEditorDragState.startY = e.clientY;

        const rect = windowEl.getBoundingClientRect();
        promptEditorDragState.startLeft = rect.left;
        promptEditorDragState.startTop = rect.top;

        // Remove transform for absolute positioning during drag
        windowEl.style.transform = 'none';
        windowEl.style.left = rect.left + 'px';
        windowEl.style.top = rect.top + 'px';

        e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
        if (!promptEditorDragState.isDragging) return;

        const deltaX = e.clientX - promptEditorDragState.startX;
        const deltaY = e.clientY - promptEditorDragState.startY;

        let newLeft = promptEditorDragState.startLeft + deltaX;
        let newTop = promptEditorDragState.startTop + deltaY;

        // Keep window within viewport bounds
        newLeft = Math.max(0, Math.min(newLeft, window.innerWidth - 100));
        newTop = Math.max(0, Math.min(newTop, window.innerHeight - 50));

        windowEl.style.left = newLeft + 'px';
        windowEl.style.top = newTop + 'px';
    });

    document.addEventListener('mouseup', () => {
        promptEditorDragState.isDragging = false;
    });
}

/**
 * Open prompt editor for a workflow step
 * @param {number} stepNumber - The step number in the workflow form
 */
async function openPromptEditorForStep(stepNumber) {
    const promptSelect = document.getElementById(`step-prompt-${stepNumber}`);
    if (!promptSelect || !promptSelect.value) {
        alert('プロンプトを先に選択してください / Please select a prompt first');
        return;
    }

    const promptId = parseInt(promptSelect.value);
    const promptName = promptSelect.options[promptSelect.selectedIndex].text;

    // Show window
    const windowEl = document.getElementById('prompt-editor-window');
    windowEl.style.display = 'flex';
    windowEl.classList.remove('minimized');

    // Reset to prompt tab
    switchPromptEditorTab('prompt');

    // Set prompt info
    document.getElementById('prompt-editor-prompt-id').value = promptId;
    document.getElementById('prompt-editor-step-number').value = stepNumber;
    document.getElementById('prompt-editor-prompt-name').textContent = promptName;
    document.getElementById('prompt-editor-status').textContent = '読み込み中...';
    document.getElementById('prompt-editor-revision-info').textContent = '';

    // Load prompt template and revisions in parallel
    try {
        const [promptResponse, revisionsResponse] = await Promise.all([
            fetch(`/api/prompts/${promptId}`),
            fetch(`/api/prompts/${promptId}/revisions`)
        ]);

        if (!promptResponse.ok) throw new Error('Failed to load prompt');

        const prompt = await promptResponse.json();
        document.getElementById('prompt-editor-template').value = prompt.prompt_template || '';
        document.getElementById('prompt-editor-status').textContent = '';

        // Load parser config to UI
        loadParserConfigToUI(prompt.parser_config);

        // Render revisions
        if (revisionsResponse.ok) {
            const revisions = await revisionsResponse.json();
            renderPromptRevisions(revisions);
            // Mark latest revision as current
            if (revisions.length > 0) {
                document.getElementById('prompt-editor-current-revision').value = revisions[0].revision;
                document.getElementById('prompt-editor-revision-info').textContent = `(Rev. ${revisions[0].revision})`;
            }
        }
    } catch (error) {
        console.error('Error loading prompt:', error);
        document.getElementById('prompt-editor-template').value = '';
        document.getElementById('prompt-editor-status').textContent = 'エラー: プロンプトの読み込みに失敗しました';
        loadParserConfigToUI({ type: 'none' });
    }
}

/**
 * Close the prompt editor window
 */
function closePromptEditor() {
    const windowEl = document.getElementById('prompt-editor-window');
    windowEl.style.display = 'none';
}

/**
 * Minimize/restore the prompt editor window
 */
function minimizePromptEditor() {
    const windowEl = document.getElementById('prompt-editor-window');
    windowEl.classList.toggle('minimized');
}

/**
 * Save the prompt template from the editor
 */
async function savePromptFromEditor() {
    const promptId = document.getElementById('prompt-editor-prompt-id').value;
    const template = document.getElementById('prompt-editor-template').value;
    const statusEl = document.getElementById('prompt-editor-status');

    if (!promptId) {
        statusEl.textContent = 'エラー: プロンプトIDがありません';
        return;
    }

    statusEl.textContent = '保存中...';

    try {
        // Build save payload with both prompt_template and parser_config
        const savePayload = {
            prompt_template: template,
            parser_config: getCurrentParserConfig()
        };

        const response = await fetch(`/api/prompts/${promptId}/revisions/latest`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(savePayload)
        });

        if (!response.ok) throw new Error('Failed to save prompt');

        const result = await response.json();

        if (result.is_new) {
            statusEl.textContent = `✓ 新しいリビジョン ${result.revision} として保存しました`;
            statusEl.style.color = '#27ae60';
            // Update current revision
            document.getElementById('prompt-editor-current-revision').value = result.revision;
            document.getElementById('prompt-editor-revision-info').textContent = `(Rev. ${result.revision})`;
            // Refresh revision list
            await loadPromptRevisions();
        } else {
            statusEl.textContent = '✓ 変更なし（同じ内容です）';
            statusEl.style.color = '#7f8c8d';
        }

        // Refresh workflow variables cache since prompt changed
        refreshWorkflowVariables();

        setTimeout(() => {
            statusEl.textContent = '';
            statusEl.style.color = '#7f8c8d';
        }, 3000);
    } catch (error) {
        console.error('Error saving prompt:', error);
        statusEl.textContent = 'エラー: 保存に失敗しました';
        statusEl.style.color = '#e74c3c';
    }
}

// ========== Prompt Editor Tab Functions ==========

/**
 * Switch between prompt and parser tabs
 * @param {string} tabId - 'prompt' or 'parser'
 */
function switchPromptEditorTab(tabId) {
    // Update tab buttons
    document.querySelectorAll('.prompt-tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabId);
    });

    // Update tab content
    document.querySelectorAll('.prompt-editor-tab-content').forEach(content => {
        const isActive = content.id === `prompt-editor-tab-${tabId}`;
        content.classList.toggle('active', isActive);
        content.style.display = isActive ? 'flex' : 'none';
    });
}

/**
 * Get current parser configuration from the UI (simple JSON textarea)
 * @returns {Object} Parser configuration object
 */
function getCurrentParserConfig() {
    const parserType = document.getElementById('prompt-editor-parser-type').value;
    const configText = document.getElementById('prompt-editor-parser-config').value.trim();

    if (parserType === 'none' || !configText) {
        return { type: 'none' };
    }

    try {
        const config = JSON.parse(configText);
        config.type = parserType;  // Ensure type matches select
        return config;
    } catch (e) {
        // Invalid JSON, return with just type
        return { type: parserType };
    }
}

/**
 * Handle parser type change - update the config textarea
 */
function onPromptEditorParserTypeChange() {
    const parserType = document.getElementById('prompt-editor-parser-type').value;
    const textarea = document.getElementById('prompt-editor-parser-config');

    // Try to parse current config
    let currentConfig = { type: parserType };
    try {
        const existing = JSON.parse(textarea.value);
        currentConfig = { ...existing, type: parserType };
    } catch (e) {
        // Create default config for type
        if (parserType === 'json_path') {
            currentConfig = { type: 'json_path', paths: {} };
        } else if (parserType === 'regex') {
            currentConfig = { type: 'regex', patterns: {} };
        } else if (parserType === 'csv_template') {
            currentConfig = { type: 'csv_template', columns: [] };
        } else {
            currentConfig = { type: 'none' };
        }
    }

    textarea.value = JSON.stringify(currentConfig, null, 2);
}

/**
 * Load parser config from API response and populate UI (simple JSON textarea)
 * @param {Object|string} parserConfig - Parser configuration
 */
function loadParserConfigToUI(parserConfig) {
    let config = parserConfig;

    // Parse if it's a string
    if (typeof config === 'string') {
        try {
            config = JSON.parse(config);
        } catch (e) {
            config = { type: 'none' };
        }
    }

    if (!config || typeof config !== 'object') {
        config = { type: 'none' };
    }

    const parserType = config.type || 'none';
    document.getElementById('prompt-editor-parser-type').value = parserType;
    document.getElementById('prompt-editor-parser-config').value = JSON.stringify(config, null, 2);
}

// ========== Prompt Revision Functions ==========

/**
 * Load and display prompt revisions
 */
async function loadPromptRevisions() {
    const promptId = document.getElementById('prompt-editor-prompt-id').value;
    if (!promptId) return;

    const listEl = document.getElementById('prompt-editor-revisions');
    listEl.innerHTML = '<li style="padding: 0.5rem; color: #9e9e9e; font-size: 0.8rem;">読み込み中...</li>';

    try {
        const response = await fetch(`/api/prompts/${promptId}/revisions`);
        if (!response.ok) throw new Error('Failed to load revisions');

        const revisions = await response.json();
        renderPromptRevisions(revisions);
    } catch (error) {
        console.error('Error loading revisions:', error);
        listEl.innerHTML = '<li style="padding: 0.5rem; color: #e74c3c; font-size: 0.8rem;">エラー</li>';
    }
}

/**
 * Render prompt revisions list
 * @param {Array} revisions - Array of revision objects
 */
function renderPromptRevisions(revisions) {
    const listEl = document.getElementById('prompt-editor-revisions');
    const currentRevision = parseInt(document.getElementById('prompt-editor-current-revision').value) || 0;

    if (!revisions || revisions.length === 0) {
        listEl.innerHTML = '<li style="padding: 0.5rem; color: #9e9e9e; font-size: 0.8rem;">リビジョンなし</li>';
        return;
    }

    let html = '';
    for (const rev of revisions) {
        const isActive = rev.revision === currentRevision;
        const isLatest = revisions[0].revision === rev.revision;
        const dateStr = formatRevisionDate(rev.created_at);

        html += `
            <li class="revision-item ${isActive ? 'active' : ''}" onclick="selectRevision(${rev.revision})" data-revision="${rev.revision}">
                <span class="rev-number">Rev. ${rev.revision}</span>
                ${isLatest ? '<span style="font-size: 0.65rem; background: #4caf50; color: white; padding: 1px 4px; border-radius: 2px; margin-left: 4px;">最新</span>' : ''}
                <span class="rev-date">${dateStr}</span>
                ${!isLatest ? `<div class="rev-actions"><button class="btn-restore" onclick="event.stopPropagation(); restoreRevision(${rev.revision})">復元</button></div>` : ''}
            </li>
        `;
    }

    listEl.innerHTML = html;
}

/**
 * Format revision date for display
 * @param {string} isoDate - ISO date string
 * @returns {string} Formatted date string
 */
function formatRevisionDate(isoDate) {
    if (!isoDate) return '';
    try {
        const date = new Date(isoDate);
        return date.toLocaleString('ja-JP', {
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
        });
    } catch (e) {
        return isoDate.substring(0, 16).replace('T', ' ');
    }
}

/**
 * Select and load a specific revision
 * @param {number} revisionNumber - The revision number to load
 */
async function selectRevision(revisionNumber) {
    const promptId = document.getElementById('prompt-editor-prompt-id').value;
    if (!promptId) return;

    const statusEl = document.getElementById('prompt-editor-status');
    statusEl.textContent = '読み込み中...';

    try {
        const response = await fetch(`/api/prompts/${promptId}/revisions`);
        if (!response.ok) throw new Error('Failed to load revisions');

        const revisions = await response.json();
        const revision = revisions.find(r => r.revision === revisionNumber);

        if (revision) {
            document.getElementById('prompt-editor-template').value = revision.prompt_template || '';
            document.getElementById('prompt-editor-current-revision').value = revisionNumber;
            document.getElementById('prompt-editor-revision-info').textContent = `(Rev. ${revisionNumber})`;

            // Load parser config for this revision
            loadParserConfigToUI(revision.parser_config);

            // Update active state in list
            document.querySelectorAll('.revision-item').forEach(el => {
                el.classList.remove('active');
                if (parseInt(el.dataset.revision) === revisionNumber) {
                    el.classList.add('active');
                }
            });

            statusEl.textContent = `Rev. ${revisionNumber} を読み込みました`;
            statusEl.style.color = '#2196f3';
            setTimeout(() => {
                statusEl.textContent = '';
                statusEl.style.color = '#7f8c8d';
            }, 2000);
        }
    } catch (error) {
        console.error('Error loading revision:', error);
        statusEl.textContent = 'エラー: リビジョンの読み込みに失敗しました';
        statusEl.style.color = '#e74c3c';
    }
}

/**
 * Restore a past revision (creates a new revision with the old content)
 * @param {number} revisionNumber - The revision number to restore
 */
async function restoreRevision(revisionNumber) {
    const promptId = document.getElementById('prompt-editor-prompt-id').value;
    if (!promptId) return;

    if (!confirm(`リビジョン ${revisionNumber} を復元しますか？\n（新しいリビジョンとして保存されます）`)) {
        return;
    }

    const statusEl = document.getElementById('prompt-editor-status');
    statusEl.textContent = '復元中...';

    try {
        const response = await fetch(`/api/prompts/${promptId}/revisions/${revisionNumber}/restore`, {
            method: 'POST'
        });

        if (!response.ok) throw new Error('Failed to restore revision');

        const result = await response.json();

        statusEl.textContent = `✓ Rev. ${revisionNumber} を Rev. ${result.revision} として復元しました`;
        statusEl.style.color = '#27ae60';

        // Update editor with restored content
        document.getElementById('prompt-editor-template').value = result.prompt_template || '';
        document.getElementById('prompt-editor-current-revision').value = result.revision;
        document.getElementById('prompt-editor-revision-info').textContent = `(Rev. ${result.revision})`;

        // Load parser config for restored revision
        loadParserConfigToUI(result.parser_config);

        // Refresh revision list
        await loadPromptRevisions();

        // Refresh workflow variables
        refreshWorkflowVariables();

        setTimeout(() => {
            statusEl.textContent = '';
            statusEl.style.color = '#7f8c8d';
        }, 3000);
    } catch (error) {
        console.error('Error restoring revision:', error);
        statusEl.textContent = 'エラー: 復元に失敗しました';
        statusEl.style.color = '#e74c3c';
    }
}
