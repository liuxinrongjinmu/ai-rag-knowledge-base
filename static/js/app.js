// 企业文档知识库问答系统前端脚本

// 问答历史记录
let conversationHistory = [];

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    loadConversationHistory();
    focusQuestionInput();
});

// 聚焦问题输入框
function focusQuestionInput() {
    document.getElementById('questionInput').focus();
}

// 发送问题 - 优化版本
async function sendQuestion() {
    const questionInput = document.getElementById('questionInput');
    const sendButton = document.getElementById('sendButton');
    const question = questionInput.value.trim();
    
    if (!question) {
        showError('请输入问题！');
        return;
    }
    
    // 立即显示用户消息（提供即时反馈）
    const currentTime = new Date().toLocaleString('zh-CN', {
        hour: '2-digit',
        minute: '2-digit'
    });
    
    const container = document.getElementById('conversationHistory');
    const userMsg = document.createElement('div');
    userMsg.className = 'd-flex justify-content-end mb-3';
    userMsg.innerHTML = `
        <div class="msg-user">
            <div class="msg-content">
                ${escapeHtml(question)}
            </div>
            <small class="text-muted">${currentTime}</small>
        </div>
    `;
    container.appendChild(userMsg);
    container.scrollTop = container.scrollHeight;
    
    // 清空输入框
    questionInput.value = '';
    questionInput.disabled = true;
    sendButton.disabled = true;
    sendButton.innerHTML = '<i class="bi bi-hourglass-split"></i> 发送中...';
    
    // 显示"正在思考"的助手消息
    const thinkingMsg = document.createElement('div');
    thinkingMsg.className = 'd-flex justify-content-start mb-3';
    thinkingMsg.innerHTML = `
        <div class="msg-assistant msg-thinking">
            <div class="msg-content">
                <i class="bi bi-robot"></i> 正在思考
                <div class="thinking-dots">
                    <span>.</span><span>.</span><span>.</span>
                </div>
            </div>
        </div>
    `;
    thinkingMsg.id = 'thinkingMessage';
    container.appendChild(thinkingMsg);
    container.scrollTop = container.scrollHeight;
    
    // 清理之前的错误信息
    hideError();
    hideQueryRewrite();
    
    // 记录开始时间
    const startTime = Date.now();
    
    try {
        // 添加超时控制
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 30000); // 30秒超时
        
        console.log('发送请求到:', '/api/query');
        console.log('请求体:', JSON.stringify({ question: question }));
        
        const response = await fetch('/api/query', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify({ question: question }),
            signal: controller.signal
        });
        
        clearTimeout(timeoutId);
        
        console.log('响应状态:', response.status);
        console.log('响应头:', response.headers);
        
        // 移除"正在思考"消息
        const thinkingMsg = document.getElementById('thinkingMessage');
        if (thinkingMsg) {
            thinkingMsg.remove();
        }
        
        // 检查响应状态
        if (!response.ok) {
            throw new Error(`HTTP错误: ${response.status} ${response.statusText}`);
        }
        
        const data = await response.json();
        
        if (data.success) {
            // 构建助手回答内容（包含来源）
            let answerText = data.answer;
            if (data.sources && data.sources.length > 0) {
                answerText += '\n\n📚 参考来源：\n' + 
                    data.sources.map(s => `• ${s.name}`).join('\n');
            }
            
            // 显示响应时间和缓存状态
            if (data.response_time) {
                const timeText = `⚡ ${data.response_time}秒`;
                if (data.from_cache) {
                    answerText += `\n\n${timeText} (缓存命中)`;
                } else {
                    answerText += `\n\n${timeText}`;
                }
            }
            
            // 显示查询改写（如果有）
            if (data.rewritten_question) {
                showQueryRewrite(question, data.rewritten_question);
            }
            
            // 显示上下文信息
            if (data.has_context) {
                showContextIndicator();
            }
            
            // 添加助手回答到对话
            const assistantTime = new Date().toLocaleString('zh-CN', {
                hour: '2-digit',
                minute: '2-digit'
            });
            const assistantMsg = document.createElement('div');
            assistantMsg.className = 'd-flex justify-content-start mb-3 fade-in';
            assistantMsg.innerHTML = `
                <div class="msg-assistant">
                    <div class="msg-content">
                        ${formatAnswer(answerText)}
                    </div>
                    <small class="text-muted">
                        <i class="bi bi-clock"></i> ${assistantTime}
                    </small>
                </div>
            `;
            container.appendChild(assistantMsg);
            container.scrollTop = container.scrollHeight;
            
            // 添加到本地历史记录
            addToHistory(question, data.answer, data.sources);
            
        } else {
            // 移除"正在思考"消息并显示错误
            if (thinkingMsg) {
                thinkingMsg.remove();
            }
            showError(data.message || '处理查询时出错！');
        }
        
        // 恢复输入状态
        questionInput.disabled = false;
        sendButton.disabled = false;
        sendButton.innerHTML = '<i class="bi bi-send"></i>';
        
    } catch (error) {
        // 移除"正在思考"消息
        const thinkingMsg = document.getElementById('thinkingMessage');
        if (thinkingMsg) {
            thinkingMsg.remove();
        }
        
        if (error.name === 'AbortError') {
            showError('查询超时，请稍后重试！');
        } else if (error.message && error.message.includes('Failed to fetch')) {
            console.error('Fetch Error:', error);
            showError('无法连接到服务器，请检查服务器是否正在运行！');
        } else if (error.message && error.message.includes('NetworkError')) {
            console.error('Network Error:', error);
            showError('网络连接错误，请检查网络连接！');
        } else {
            console.error('Unknown Error:', error);
            showError(`请求失败: ${error.message || '未知错误'}`);
        }
        
        // 恢复输入状态
        questionInput.disabled = false;
        sendButton.disabled = false;
        sendButton.innerHTML = '<i class="bi bi-send"></i>';
    } finally {
        hideLoading();
        focusQuestionInput();
        
        // 记录总时间
        const totalTime = (Date.now() - startTime) / 1000;
        console.log(`查询总耗时: ${totalTime.toFixed(2)}秒`);
    }
}

// 显示响应时间（已集成到消息显示中）
function showResponseTime(responseTime, fromCache = false) {
    // 此功能已集成到sendQuestion函数中
    console.log(`响应时间: ${responseTime}秒, 缓存: ${fromCache ? '命中' : '未命中'}`);
}

// 显示加载状态 - 优化版本（现在主要用于初始加载）
function showLoading() {
    // 由于我们现在有了更好的实时状态反馈，这个函数主要用于特殊情况
    console.log('系统处理中...');
}

// 隐藏加载状态
function hideLoading() {
    // 加载状态现在集成在sendQuestion函数中
    console.log('处理完成');
}

// 显示错误信息
function showError(message) {
    const errorElement = document.getElementById('errorMessage');
    const errorText = document.getElementById('errorText');
    errorText.textContent = message;
    errorElement.style.display = 'block';
    errorElement.classList.add('fade-in');
}

// 隐藏错误信息
function hideError() {
    document.getElementById('errorMessage').style.display = 'none';
}

// 显示查询改写
function showQueryRewrite(original, rewritten) {
    const rewriteElement = document.getElementById('queryRewrite');
    const rewriteText = document.getElementById('rewriteText');
    rewriteText.textContent = `"${original}" → "${rewritten}"`;
    rewriteElement.style.display = 'block';
    rewriteElement.classList.add('fade-in');
}

// 隐藏查询改写
function hideQueryRewrite() {
    document.getElementById('queryRewrite').style.display = 'none';
}

// 显示答案（已集成到sendQuestion函数中）
function showAnswer(answer, sources) {
    // 此功能已集成到sendQuestion函数中的消息显示逻辑
    console.log('显示答案:', answer.substring(0, 50) + '...');
}

// 格式化答案文本
function formatAnswer(text) {
    // 处理换行和格式
    return text
        .replace(/\n/g, '<br>')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>');
}

// 添加到历史记录
function addToHistory(question, answer, sources) {
    const historyItem = {
        question: question,
        answer: answer,
        sources: sources,
        timestamp: new Date().toLocaleString()
    };
    
    conversationHistory.unshift(historyItem);
    
    // 限制历史记录数量
    if (conversationHistory.length > 10) {
        conversationHistory = conversationHistory.slice(0, 10);
    }
    
    updateHistoryDisplay();
    saveConversationHistory();
}

// 更新历史记录显示（现在使用服务器端对话历史）
function updateHistoryDisplay() {
    // 此功能已被服务器端对话历史替代
    console.log('本地历史记录更新:', conversationHistory.length, '条');
}

// 询问历史问题
function askHistoryQuestion(question) {
    document.getElementById('questionInput').value = question;
    sendQuestion();
}

// 清空历史记录
function clearHistory() {
    if (confirm('确定要清空所有历史记录吗？')) {
        conversationHistory = [];
        updateHistoryDisplay();
        localStorage.removeItem('conversationHistory');
    }
}

// 保存历史记录到本地存储
function saveConversationHistory() {
    try {
        localStorage.setItem('conversationHistory', JSON.stringify(conversationHistory));
    } catch (error) {
        console.error('保存历史记录失败:', error);
    }
}

// 从服务器端加载对话历史
async function loadConversationHistory() {
    try {
        const response = await fetch('/api/conversation/history');
        const data = await response.json();
        
        if (data.success && data.history && data.history.length > 0) {
            displayConversationHistory(data.history);
        }
    } catch (error) {
        console.error('加载对话历史失败:', error);
    }
}

// 显示对话历史
function displayConversationHistory(history) {
    const container = document.getElementById('conversationHistory');
    
    // 保留欢迎消息，清空其他内容
    const welcomeMsg = container.querySelector('.d-flex:first-child');
    container.innerHTML = '';
    if (welcomeMsg) {
        container.appendChild(welcomeMsg);
    }
    
    history.forEach((exchange) => {
        const currentTime = new Date(exchange.timestamp).toLocaleString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit'
        });
        
        // 用户问题
        const userMsg = document.createElement('div');
        userMsg.className = 'd-flex justify-content-end mb-3';
        userMsg.innerHTML = `
            <div class="msg-user">
                <div class="msg-content">
                    ${escapeHtml(exchange.question)}
                </div>
                <small class="text-muted">${currentTime}</small>
            </div>
        `;
        
        // 助手回答
        let answerText = exchange.answer;
        if (exchange.sources && exchange.sources.length > 0) {
            answerText += '\n\n📚 参考来源：\n' + 
                exchange.sources.map(s => `• ${s.name}`).join('\n');
        }
        
        const assistantMsg = document.createElement('div');
        assistantMsg.className = 'd-flex justify-content-start mb-3';
        assistantMsg.innerHTML = `
            <div class="msg-assistant">
                <div class="msg-content">
                    ${formatAnswer(answerText)}
                </div>
                <small class="text-muted">
                    <i class="bi bi-clock"></i> ${currentTime}
                </small>
            </div>
        `;
        
        container.appendChild(userMsg);
        container.appendChild(assistantMsg);
    });
    
    // 滚动到底部
    container.scrollTop = container.scrollHeight;
}







// 清空对话
async function clearConversation() {
    if (!confirm('确定要开始新的对话吗？当前对话历史将被清空。')) {
        return;
    }
    
    try {
        const response = await fetch('/api/conversation/clear', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        // 检查响应状态
        if (!response.ok) {
            throw new Error(`HTTP错误: ${response.status} ${response.statusText}`);
        }
        
        const data = await response.json();
        
        if (data.success) {
            // 清空显示但保留欢迎消息
            const container = document.getElementById('conversationHistory');
            const welcomeMsg = container.querySelector('.d-flex:first-child');
            container.innerHTML = '';
            if (welcomeMsg) {
                container.appendChild(welcomeMsg);
            }
            
            // 显示成功提示
            showSuccessMessage('新对话已开始！');
        } else {
            showError('清空对话失败：' + (data.message || '未知错误'));
        }
    } catch (error) {
        console.error('清空对话失败:', error);
        showError('清空对话失败，请稍后重试');
    }
}

// 显示上下文指示器
function showContextIndicator() {
    showTempMessage('🧠 结合了对话上下文进行回答', 'info');
}

// 显示临时消息
function showTempMessage(message, type = 'info') {
    const tempDiv = document.getElementById('tempMessage');
    const tempText = document.getElementById('tempMessageText');
    
    tempDiv.className = `alert alert-${type} alert-sm mb-2`;
    tempText.textContent = message;
    tempDiv.style.display = 'block';
    
    // 3秒后自动隐藏
    setTimeout(() => {
        tempDiv.style.display = 'none';
    }, 3000);
}

// 显示成功消息
function showSuccessMessage(message) {
    const successDiv = document.createElement('div');
    successDiv.className = 'alert alert-success alert-dismissible fade show position-fixed';
    successDiv.style.cssText = 'top: 20px; right: 20px; z-index: 1050; min-width: 300px;';
    successDiv.innerHTML = `
        <i class="bi bi-check-circle"></i> ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    document.body.appendChild(successDiv);
    
    // 3秒后自动移除
    setTimeout(() => {
        if (successDiv.parentNode) {
            successDiv.remove();
        }
    }, 3000);
}

// HTML转义
function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

// 快捷键支持
document.addEventListener('keydown', function(event) {
    // Ctrl/Cmd + K 快速聚焦搜索框
    if ((event.ctrlKey || event.metaKey) && event.key === 'k') {
        event.preventDefault();
        focusQuestionInput();
    }
    
    // Escape 键清空输入
    if (event.key === 'Escape') {
        document.getElementById('questionInput').value = '';
    }
});

// 自动调整文本框高度（如果改为textarea）
function autoResize(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = textarea.scrollHeight + 'px';
}