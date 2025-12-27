// 管理仪表板脚本

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    initializeFileUpload();
    refreshKBInfo();
    loadConversationStats();
});

// 初始化文件上传
function initializeFileUpload() {
    const fileInput = document.getElementById('fileInput');
    const fileList = document.getElementById('fileList');
    const uploadForm = document.getElementById('uploadForm');
    
    // 文件选择变化事件
    fileInput.addEventListener('change', function() {
        const files = this.files;
        
        if (files.length === 0) {
            fileList.innerHTML = '<p class="text-muted mb-0">尚未选择文件</p>';
            return;
        }
        
        let html = '';
        for (let i = 0; i < files.length; i++) {
            const file = files[i];
            const fileSize = formatFileSize(file.size);
            
            html += `
                <div class="file-item">
                    <i class="bi bi-file-earmark-pdf"></i>
                    ${file.name}
                    <span class="text-muted ms-2">(${fileSize})</span>
                </div>
            `;
        }
        
        fileList.innerHTML = html;
    });
    
    // 表单提交事件
    uploadForm.addEventListener('submit', function(e) {
        e.preventDefault();
        uploadFiles();
    });
}

// 格式化文件大小
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// 清空文件列表
function clearFileList() {
    document.getElementById('fileInput').value = '';
    document.getElementById('fileList').innerHTML = '<p class="text-muted mb-0">尚未选择文件</p>';
}

// 上传文件
async function uploadFiles() {
    const fileInput = document.getElementById('fileInput');
    const files = fileInput.files;
    
    if (files.length === 0) {
        alert('请选择要上传的文件！');
        return;
    }
    
    const formData = new FormData();
    for (let i = 0; i < files.length; i++) {
        formData.append('files', files[i]);
    }
    
    // 显示上传进度
    showUploadProgress();
    
    try {
        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (data.success) {
            showSuccessMessage(data.message);
            clearFileList();
            refreshKBInfo();
            
            // 刷新文档列表显示
            setTimeout(() => {
                location.reload();
            }, 2000);
        } else {
            showErrorMessage(data.message || '上传失败！');
        }
    } catch (error) {
        console.error('Upload error:', error);
        showErrorMessage('网络连接出错，请稍后重试！');
    } finally {
        hideUploadProgress();
    }
}

// 显示上传进度
function showUploadProgress() {
    const progress = document.getElementById('uploadProgress');
    const progressBar = progress.querySelector('.progress-bar');
    
    progress.style.display = 'block';
    progressBar.style.width = '0%';
    
    // 模拟上传进度
    let progressValue = 0;
    const interval = setInterval(() => {
        progressValue += Math.random() * 30;
        if (progressValue > 90) progressValue = 90;
        
        progressBar.style.width = progressValue + '%';
        
        if (progressValue >= 90) {
            clearInterval(interval);
        }
    }, 500);
    
    progress.dataset.interval = interval;
}

// 隐藏上传进度
function hideUploadProgress() {
    const progress = document.getElementById('uploadProgress');
    const progressBar = progress.querySelector('.progress-bar');
    
    if (progress.dataset.interval) {
        clearInterval(progress.dataset.interval);
    }
    
    // 完成动画
    progressBar.style.width = '100%';
    
    setTimeout(() => {
        progress.style.display = 'none';
    }, 1000);
}

// 刷新知识库信息
async function refreshKBInfo() {
    try {
        const response = await fetch('/api/kb_info');
        const data = await response.json();
        
        if (data) {
            updateKBDisplay(data);
        }
    } catch (error) {
        console.error('Failed to refresh KB info:', error);
    }
}

// 更新知识库显示
function updateKBDisplay(docInfo) {
    // 更新统计数字
    const totalDocuments = document.querySelector('.bg-primary h3');
    const totalChunks = document.querySelector('.bg-success h3');
    const lastUpdated = document.querySelector('.bg-info p');
    
    if (totalDocuments) totalDocuments.textContent = docInfo.total_documents || 0;
    if (totalChunks) totalChunks.textContent = docInfo.total_chunks || 0;
    if (lastUpdated) lastUpdated.textContent = docInfo.last_updated || '未知';
    
    // 显示缓存统计（如果有）
    if (docInfo.cache) {
        updateCacheStats(docInfo.cache);
    }
    
    // 更新对话统计
    await loadConversationStats();
    
    // 更新文档列表
    updateDocumentList(docInfo.sources || []);
}

// 更新文档列表
function updateDocumentList(sources) {
    const documentList = document.getElementById('documentList');
    
    if (sources.length === 0) {
        documentList.innerHTML = `
            <div class="text-center text-muted">
                <i class="bi bi-inbox fs-1"></i>
                <p class="mt-2">暂无文档，请上传PDF文件</p>
            </div>
        `;
        return;
    }
    
    let html = '<div class="row">';
    sources.forEach(source => {
        html += `
            <div class="col-md-6 col-lg-4 mb-3">
                <div class="card border-secondary">
                    <div class="card-body text-center">
                        <i class="bi bi-file-earmark-pdf text-danger fs-3"></i>
                        <h6 class="mt-2">${source}</h6>
                        <small class="text-muted">已入库</small>
                    </div>
                </div>
            </div>
        `;
    });
    html += '</div>';
    
    documentList.innerHTML = html;
}

// 重建知识库
function rebuildKnowledgeBase() {
    const modal = new bootstrap.Modal(document.getElementById('confirmModal'));
    const confirmMessage = document.getElementById('confirmMessage');
    const confirmButton = document.getElementById('confirmButton');
    
    confirmMessage.textContent = '重建知识库将删除现有数据并重新处理所有PDF文档，此过程可能需要较长时间。确定要继续吗？';
    
    confirmButton.onclick = async function() {
        modal.hide();
        
        try {
            const response = await fetch('/api/rebuild_kb', {
                method: 'POST'
            });
            
            const data = await response.json();
            
            if (data.success) {
                showSuccessMessage(data.message);
                refreshKBInfo();
            } else {
                showErrorMessage(data.message || '重建失败！');
            }
        } catch (error) {
            console.error('Rebuild error:', error);
            showErrorMessage('重建过程中出错！');
        }
    };
    
    modal.show();
}

// 加载对话统计信息
async function loadConversationStats() {
    try {
        const response = await fetch('/api/conversation/stats');
        const data = await response.json();
        
        if (data.success && data.stats) {
            document.getElementById('totalConversations').textContent = data.stats.total_conversations;
            document.getElementById('totalExchanges').textContent = data.stats.total_exchanges;
        } else {
            // 如果获取失败，显示默认值
            document.getElementById('totalConversations').textContent = '0';
            document.getElementById('totalExchanges').textContent = '0';
        }
    } catch (error) {
        console.error('加载对话统计失败:', error);
        // 不显示错误消息，避免干扰用户体验
        document.getElementById('totalConversations').textContent = '0';
        document.getElementById('totalExchanges').textContent = '0';
    }
}

// 下载知识库信息
function downloadKBInfo() {
    fetch('/api/kb_info')
        .then(response => response.json())
        .then(data => {
            const infoText = `
知识库信息报告
生成时间：${new Date().toLocaleString()}

文档数量：${data.total_documents}
文本块数量：${data.total_chunks}
最后更新：${data.last_updated}

文档列表：
${data.sources ? data.sources.map(source => `- ${source}`).join('\n') : '无'}

---
企业文档知识库系统
            `;
            
            const blob = new Blob([infoText], { type: 'text/plain;charset=utf-8' });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `知识库信息报告_${new Date().toISOString().split('T')[0]}.txt`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
            
            showSuccessMessage('报告已下载！');
        })
        .catch(error => {
            console.error('Download error:', error);
            showErrorMessage('下载失败！');
        });
}

// 显示成功消息
function showSuccessMessage(message) {
    const alertHtml = `
        <div class="alert alert-success alert-dismissible fade show" role="alert">
            <i class="bi bi-check-circle"></i> ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `;
    
    insertAlert(alertHtml);
}

// 显示错误消息
function showErrorMessage(message) {
    const alertHtml = `
        <div class="alert alert-danger alert-dismissible fade show" role="alert">
            <i class="bi bi-exclamation-triangle"></i> ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `;
    
    insertAlert(alertHtml);
}

// 插入提示消息
function insertAlert(html) {
    const container = document.querySelector('.container');
    const firstRow = container.querySelector('.row');
    
    const alertDiv = document.createElement('div');
    alertDiv.innerHTML = html;
    const alert = alertDiv.firstElementChild;
    
    container.insertBefore(alert, firstRow);
    
    // 自动消失
    setTimeout(() => {
        if (alert.parentNode) {
            alert.remove();
        }
    }, 5000);
}

// 拖拽上传支持
document.addEventListener('DOMContentLoaded', function() {
    const fileInput = document.getElementById('fileInput');
    const fileList = document.getElementById('fileList');
    
    if (!fileList) return;
    
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        fileList.addEventListener(eventName, preventDefaults, false);
    });
    
    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }
    
    ['dragenter', 'dragover'].forEach(eventName => {
        fileList.addEventListener(eventName, highlight, false);
    });
    
    ['dragleave', 'drop'].forEach(eventName => {
        fileList.addEventListener(eventName, unhighlight, false);
    });
    
    function highlight(e) {
        fileList.style.backgroundColor = '#e3f2fd';
        fileList.style.borderColor = '#2196f3';
    }
    
    function unhighlight(e) {
        fileList.style.backgroundColor = '#f8f9fa';
        fileList.style.borderColor = '#dee2e6';
    }
    
    fileList.addEventListener('drop', handleDrop, false);
    
    function handleDrop(e) {
        const dt = e.dataTransfer;
        const files = dt.files;
        
        fileInput.files = files;
        
        // 触发change事件
        const event = new Event('change', { bubbles: true });
        fileInput.dispatchEvent(event);
    }
});

// 缓存管理功能
function updateCacheStats(cacheData) {
    // 在统计卡片中显示缓存信息
    const cacheBadge = document.createElement('span');
    cacheBadge.className = 'badge bg-info ms-2';
    cacheBadge.title = `缓存命中率: ${(cacheData.hit_rate * 100).toFixed(1)}%`;
    cacheBadge.textContent = `${cacheData.size}/${cacheData.max_size}`;
    
    // 查找文档数量卡片并添加缓存信息
    const documentsCard = document.querySelector('.bg-primary .card-title');
    if (documentsCard && !documentsCard.querySelector('.badge')) {
        documentsCard.appendChild(cacheBadge);
    }
}

function showCacheStats() {
    fetch('/api/kb_info')
        .then(response => response.json())
        .then(data => {
            if (data.cache) {
                const hitRate = (data.cache.hit_rate * 100).toFixed(1);
                const message = `
缓存统计信息：
• 缓存大小：${data.cache.size}/${data.cache.max_size}
• 命中率：${hitRate}%
• 缓存有助于大幅提升重复查询的响应速度
                `;
                
                const modal = new bootstrap.Modal(document.getElementById('confirmModal'));
                const confirmMessage = document.getElementById('confirmMessage');
                const confirmButton = document.getElementById('confirmButton');
                
                confirmMessage.innerHTML = `<pre class="text-start">${message}</pre>`;
                confirmButton.textContent = '关闭';
                confirmButton.className = 'btn btn-primary';
                confirmButton.onclick = () => modal.hide();
                
                // 隐藏取消按钮
                const cancelButton = confirmButton.nextElementSibling;
                if (cancelButton && cancelButton.textContent === '取消') {
                    cancelButton.style.display = 'none';
                }
                
                modal.show();
            }
        })
        .catch(error => {
            console.error('Failed to get cache stats:', error);
            showErrorMessage('获取缓存统计失败！');
        });
}

function clearCache() {
    const modal = new bootstrap.Modal(document.getElementById('confirmModal'));
    const confirmMessage = document.getElementById('confirmMessage');
    const confirmButton = document.getElementById('confirmButton');
    
    confirmMessage.textContent = '清空缓存将删除所有查询历史记录，后续查询会变慢，直到缓存重新建立。确定要继续吗？';
    
    confirmButton.onclick = async function() {
        modal.hide();
        
        try {
            const response = await fetch('/api/cache/clear', {
                method: 'POST'
            });
            
            const data = await response.json();
            
            if (data.success) {
                showSuccessMessage(data.message);
                refreshKBInfo(); // 刷新显示
            } else {
                showErrorMessage(data.message || '清空缓存失败！');
            }
        } catch (error) {
            console.error('Clear cache error:', error);
            showErrorMessage('清空缓存时出错！');
        }
    };
    
    modal.show();
}

// 加载对话统计信息
async function loadConversationStats() {
    try {
        const response = await fetch('/api/conversation/stats');
        const data = await response.json();
        
        if (data.success && data.stats) {
            document.getElementById('totalConversations').textContent = data.stats.total_conversations;
            document.getElementById('totalExchanges').textContent = data.stats.total_exchanges;
        } else {
            // 如果获取失败，显示默认值
            document.getElementById('totalConversations').textContent = '0';
            document.getElementById('totalExchanges').textContent = '0';
        }
    } catch (error) {
        console.error('加载对话统计失败:', error);
        // 不显示错误消息，避免干扰用户体验
        document.getElementById('totalConversations').textContent = '0';
        document.getElementById('totalExchanges').textContent = '0';
    }
}