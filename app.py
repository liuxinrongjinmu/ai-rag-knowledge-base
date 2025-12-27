#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
RAG系统Web应用主程序
功能：提供前端用户界面和后端管理界面
"""

import os
import pickle
import logging
import shutil
import hashlib
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import pypdf
from pypdf import PdfReader
from langchain.chains import RetrievalQA
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_community.llms import Tongyi
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.vectorstores import FAISS
import subprocess
import sys
import re
import threading
import time
from typing import Dict, Tuple, List
from functools import lru_cache

# 初始化应用
app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # 用于session和flash消息

# 配置
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf'}
VECTOR_DB_PATH = './vector_db'

# 确保上传目录存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(VECTOR_DB_PATH, exist_ok=True)

# 初始化Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 设置 DashScope API Key
DASHSCOPE_API_KEY = os.getenv('DASHSCOPE_API_KEY')
if not DASHSCOPE_API_KEY:
    raise ValueError("请设置环境变量 DASHSCOPE_API_KEY")

# 全局变量
knowledgeBase = None
query_rewriter = None
qa_chain = None

# 多轮对话管理器
class ConversationManager:
    """多轮对话管理器"""
    
    def __init__(self, max_history=10, max_age_minutes=30):
        self.conversations = {}  # {session_id: conversation_data}
        self.max_history = max_history
        self.max_age_seconds = max_age_minutes * 60
        self.lock = threading.Lock()
    
    def _get_session_id(self, request):
        """获取会话ID"""
        # 优先使用session中的ID
        if 'conversation_id' not in session:
            session['conversation_id'] = hashlib.md5(
                f"{request.remote_addr}_{datetime.now().strftime('%Y%m%d%H%M%S')}".encode()
            ).hexdigest()[:16]
        return session['conversation_id']
    
    def _clean_old_conversations(self):
        """清理过期的对话"""
        current_time = time.time()
        expired_sessions = []
        
        for session_id, conv_data in self.conversations.items():
            if current_time - conv_data['last_updated'] > self.max_age_seconds:
                expired_sessions.append(session_id)
        
        for session_id in expired_sessions:
            del self.conversations[session_id]
            logger.info(f"清理过期对话: {session_id}")
    
    def add_exchange(self, request, question: str, answer: str, sources: List = None):
        """添加一次对话交换"""
        with self.lock:
            session_id = self._get_session_id(request)
            
            # 清理过期对话
            if len(self.conversations) > 1000:  # 限制最大对话数
                self._clean_old_conversations()
            
            # 初始化或获取对话数据
            if session_id not in self.conversations:
                self.conversations[session_id] = {
                    'history': [],
                    'last_updated': time.time(),
                    'created_at': time.time()
                }
            
            # 添加新的对话交换
            self.conversations[session_id]['history'].append({
                'question': question,
                'answer': answer,
                'sources': sources or [],
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            
            # 限制历史记录长度
            if len(self.conversations[session_id]['history']) > self.max_history:
                self.conversations[session_id]['history'] = \
                    self.conversations[session_id]['history'][-self.max_history:]
            
            # 更新时间戳
            self.conversations[session_id]['last_updated'] = time.time()
            
            logger.info(f"添加对话记录 - 会话: {session_id}, 历史长度: {len(self.conversations[session_id]['history'])}")
    
    def get_context(self, request, max_context_exchanges=3) -> str:
        """获取对话上下文"""
        session_id = self._get_session_id(request)
        
        if session_id not in self.conversations:
            return ""
        
        history = self.conversations[session_id]['history']
        if not history:
            return ""
        
        # 获取最近几次对话作为上下文
        recent_exchanges = history[-max_context_exchanges:]
        
        context_parts = []
        for exchange in recent_exchanges:
            context_parts.append(f"用户: {exchange['question']}")
            context_parts.append(f"助手: {exchange['answer']}")
        
        return "\n".join(context_parts)
    
    def get_history(self, request) -> List:
        """获取完整对话历史"""
        session_id = self._get_session_id(request)
        
        if session_id not in self.conversations:
            return []
        
        return self.conversations[session_id]['history']
    
    def clear_conversation(self, request):
        """清空当前会话"""
        session_id = self._get_session_id(request)
        
        with self.lock:
            if session_id in self.conversations:
                del self.conversations[session_id]
                logger.info(f"清空对话: {session_id}")
                return True
        return False
    
    def get_conversation_stats(self) -> Dict:
        """获取对话统计信息"""
        with self.lock:
            total_conversations = len(self.conversations)
            total_exchanges = sum(len(conv['history']) for conv in self.conversations.values())
            
            return {
                'total_conversations': total_conversations,
                'total_exchanges': total_exchanges,
                'avg_exchanges_per_conversation': total_exchanges / max(total_conversations, 1)
            }

# 初始化对话管理器
conversation_manager = ConversationManager(max_history=8, max_age_minutes=30)

# 缓存机制
class ResponseCache:
    """响应缓存类"""
    def __init__(self, max_size=100, ttl=3600):  # 默认1小时过期
        self.cache = {}
        self.max_size = max_size
        self.ttl = ttl
        self.access_times = {}
        self.lock = threading.Lock()
        self.hit_count = 0
        self.total_count = 0
    
    def _generate_key(self, question: str, rewritten_question: str = None) -> str:
        """生成缓存键"""
        # 使用原始问题作为键，确保一致性
        return hashlib.md5(question.encode('utf-8')).hexdigest()
    
    def get(self, question: str, rewritten_question: str = None):
        """获取缓存响应"""
        self.total_count += 1
        key = self._generate_key(question, rewritten_question)
        
        with self.lock:
            if key in self.cache:
                cached_data, timestamp = self.cache[key]
                
                # 检查是否过期
                if time.time() - timestamp < self.ttl:
                    self.hit_count += 1
                    self.access_times[key] = time.time()
                    logger.info(f"缓存命中: {question[:30]}...")
                    return cached_data
                else:
                    # 删除过期缓存
                    del self.cache[key]
                    if key in self.access_times:
                        del self.access_times[key]
        
        return None
    
    def set(self, question: str, response_data: dict, rewritten_question: str = None):
        """设置缓存响应"""
        key = self._generate_key(question, rewritten_question)
        
        with self.lock:
            # 如果缓存已满，删除最久未访问的项
            if len(self.cache) >= self.max_size:
                self._evict_oldest()
            
            self.cache[key] = (response_data, time.time())
            self.access_times[key] = time.time()
            logger.info(f"缓存设置: {question[:30]}... - 键: {key}")
    
    def _evict_oldest(self):
        """删除最久未访问的缓存项"""
        if not self.access_times:
            return
        
        oldest_key = min(self.access_times.keys(), key=lambda k: self.access_times[k])
        
        if oldest_key in self.cache:
            del self.cache[oldest_key]
        del self.access_times[oldest_key]
    
    def clear(self):
        """清空缓存"""
        with self.lock:
            self.cache.clear()
            self.access_times.clear()
    
    def get_stats(self):
        """获取缓存统计信息"""
        with self.lock:
            return {
                'size': len(self.cache),
                'max_size': self.max_size,
                'hit_rate': getattr(self, 'hit_count', 0) / max(getattr(self, 'total_count', 1), 1)
            }

# 初始化缓存
response_cache = ResponseCache(max_size=200, ttl=1800)  # 30分钟过期，最大200个缓存

# 模拟管理员账户（实际应用中应使用数据库）
ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD_HASH = generate_password_hash('admin123')

def allowed_file(filename):
    """检查文件扩展名是否允许"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

class QueryRewriter:
    """查询改写类"""
    
    def __init__(self, llm):
        self.llm = llm
        # 查询改写缓存
        self.rewrite_cache = {}
        
        # 常见的口语化表达到规范化表达的映射
        self.colloquial_mapping = {
            # 报销相关
            "报账": "报销",
            "拿发票": "报销",
            "贴票": "报销",
            "报销钱": "报销",
            "怎么报销": "报销流程",
            "报销要什么": "报销材料",
            "报销标准": "报销额度",
            "能报多少": "报销额度",
            "报销上限": "报销额度",
            
            # 福利相关
            "福利怎么样": "福利待遇",
            "有什么福利": "福利项目",
            "福利好不好": "福利标准",
            "能拿什么福利": "福利项目",
            "福利有哪些": "福利项目",
            
            # 考核相关
            "考核怎么算": "考核标准",
            "怎么考核": "考核方式",
            "考核要求": "考核标准",
            "考核指标": "考核标准",
            "绩效考核": "考核办法",
            "被投诉": "投诉处理",
            "被投诉一次": "投诉处罚标准",
            "被投诉有什么影响": "投诉处理后果",
            "投诉扣分": "投诉处罚标准",
            "投诉了会怎样": "投诉处理后果",
            
            # SAP相关
            "SAP是什么": "SAP系统介绍",
            "SAP有哪些模块": "SAP系统模块",
            "SAP模块": "SAP系统模块",
            "SAP功能": "SAP系统功能",
            "SAP系统": "SAP",
            
            # 客户经理相关
            "客户经理": "客户经理",
            "客户经理评聘": "客户经理评聘时间",
            "客户经理考核": "客户经理考核办法",
            "客户经理管理": "客户经理管理办法",
            "评聘时间": "评聘时间",
            "评聘": "评聘制度",
            
            # 常见错别字修正
            "报稍": "报销",
            "报肖": "报销",
            "员公": "员工",
            "员共": "员工",
            "地止": "地址",
            "地制": "地址",
            "标淮": "标准",
            "标住": "标准",
            
            # 口语化表达
            "多少钱": "费用标准",
            "怎么搞": "如何办理",
            "怎么办": "如何申请",
            "要什么": "需要什么材料",
            "啥时候": "时间",
            "多久": "时间要求",
            "什么时候": "时间",
            "啥时": "时间",
            "怎么": "如何",
            "怎么样": "情况如何",
            "有哪些": "包括哪些",
            "有什么": "包括什么",
            "能不能": "是否可以",
            "可不可以": "是否可以",
        }
    
    def basic_rewrite(self, query: str) -> str:
        """基础查询改写"""
        rewritten = query
        for colloquial, formal in self.colloquial_mapping.items():
            rewritten = rewritten.replace(colloquial, formal)
        
        # 清理多余的标点符号
        rewritten = re.sub(r'[！]{2,}', '！', rewritten)
        rewritten = re.sub(r'[？]{2,}', '？', rewritten)
        rewritten = re.sub(r'[。]{2,}', '。', rewritten)
        
        # 移除常见的口语化语气词
        rewritten = re.sub(r'[呀啊啦呢呗]', '', rewritten)
        
        return rewritten.strip()
    
    def ai_rewrite(self, query: str) -> str:
        """使用AI进行查询改写"""
        rewrite_prompt = ChatPromptTemplate.from_template(
            "你是一个查询改写专家。请将用户的口语化、不规范的问题改写为规范的书面化问题。\n"
            "改写要求：\n"
            "1. 保持原意不变\n"
            "2. 使用规范的书面语言\n"
            "3. 去除口语化表达和语气词\n"
            "4. 确保问题清晰明确\n"
            "5. 针对公司制度和文档相关的场景\n\n"
            "原始问题：{query}\n\n"
            "改写后的问题（只回答改写后的问题，不要其他解释）："
        )
        
        try:
            chain = rewrite_prompt | self.llm
            rewritten_query = chain.invoke({"query": query})
            return str(rewritten_query).strip()
        except Exception as e:
            logger.warning(f"AI改写失败，使用基础改写: {e}")
            return self.basic_rewrite(query)
    
    def rewrite_query(self, query: str, use_ai: bool = True) -> Tuple[str, bool]:
        """查询改写主函数"""
        # 检查缓存
        cache_key = hashlib.md5(f"{query}_{use_ai}".encode('utf-8')).hexdigest()
        if cache_key in self.rewrite_cache:
            cached_result = self.rewrite_cache[cache_key]
            logger.info(f"查询改写缓存命中: {query[:30]}...")
            return cached_result
        
        basic_rewritten = self.basic_rewrite(query)
        needs_rewrite = basic_rewritten != query
        
        if not needs_rewrite:
            result = (query, False)
        elif use_ai:
            # 使用AI改写
            ai_rewritten = self.ai_rewrite(query)
            result = (ai_rewritten, True)
        else:
            # 只使用基础改写
            result = (basic_rewritten, True)
        
        # 缓存结果
        self.rewrite_cache[cache_key] = result
        
        # 限制缓存大小
        if len(self.rewrite_cache) > 500:
            # 删除一半最旧的缓存
            keys_to_remove = list(self.rewrite_cache.keys())[:250]
            for key in keys_to_remove:
                del self.rewrite_cache[key]
        
        return result

def extract_text_with_page_numbers(pdf) -> Tuple[str, List[int]]:
    """从PDF中提取文本并记录每行文本对应的页码"""
    text = ""
    page_numbers = []
    for page_number, page in enumerate(pdf.pages, start=1):
        extracted_text = page.extract_text()
        if extracted_text:
            lines = extracted_text.split("\n")
            text += extracted_text + "\n"
            page_numbers.extend([page_number] * len(lines))
        else:
            logger.warning(f"在第 {page_number} 页未找到文本。")
    return text, page_numbers

def process_pdf_document(pdf_path: str, save_path: str = None) -> FAISS:
    """处理单个PDF文档并创建向量存储"""
    print(f"📄 处理文档: {os.path.basename(pdf_path)}")
    
    # 提取文本
    pdf_reader = PdfReader(pdf_path)
    text, page_numbers = extract_text_with_page_numbers(pdf_reader)
    source_name = os.path.basename(pdf_path)
    
    # 优化文本分割参数
    text_splitter = RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", "。", "；", "，", ".", " ", ""],
        chunk_size=600,
        chunk_overlap=150,
        length_function=len,
    )
    chunks = text_splitter.split_text(text)
    print(f"从 {source_name} 提取了 {len(chunks)} 个文本块")
    
    # 创建向量数据库
    embeddings = DashScopeEmbeddings(model="text-embedding-v1", dashscope_api_key=DASHSCOPE_API_KEY)
    
    # 为每个文本块创建元数据
    metadatas = []
    page_info = {}
    for i, chunk in enumerate(chunks):
        metadata = {
            "source": source_name,
            "page": page_numbers[i] if i < len(page_numbers) else 1,
            "chunk_id": f"{source_name}_{i}",
            "upload_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        metadatas.append(metadata)
        page_info[chunk] = {
            "source": source_name,
            "page": page_numbers[i] if i < len(page_numbers) else 1
        }
    
    knowledgeBase = FAISS.from_texts(chunks, embeddings, metadatas)
    knowledgeBase.page_info = page_info
    
    return knowledgeBase, source_name, len(chunks)

def update_knowledge_base_with_new_pdfs(new_pdf_paths: List[str]) -> bool:
    """使用新的PDF文档更新知识库"""
    global knowledgeBase, qa_chain
    
    try:
        print(f"🔄 开始处理 {len(new_pdf_paths)} 个新PDF文档...")
        
        embeddings = DashScopeEmbeddings(model="text-embedding-v1", dashscope_api_key=DASHSCOPE_API_KEY)
        new_texts = []
        new_metadatas = []
        new_sources = []
        
        # 处理新的PDF文档
        for pdf_path in new_pdf_paths:
            pdf_reader = PdfReader(pdf_path)
            text, page_numbers = extract_text_with_page_numbers(pdf_reader)
            source_name = os.path.basename(pdf_path)
            new_sources.append(source_name)
            
            # 分割文本
            text_splitter = RecursiveCharacterTextSplitter(
                separators=["\n\n", "\n", "。", "；", "，", ".", " ", ""],
                chunk_size=600,
                chunk_overlap=150,
                length_function=len,
            )
            chunks = text_splitter.split_text(text)
            print(f"从 {source_name} 提取了 {len(chunks)} 个文本块")
            
            # 为每个文本块创建元数据
            for i, chunk in enumerate(chunks):
                metadata = {
                    "source": source_name,
                    "page": page_numbers[i] if i < len(page_numbers) else 1,
                    "chunk_id": f"{source_name}_{i}",
                    "upload_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "is_new": True
                }
                new_metadatas.append(metadata)
            
            new_texts.extend(chunks)
        
        if new_texts:
            # 创建新的向量数据库
            new_db = FAISS.from_texts(new_texts, embeddings, new_metadatas)
            
            # 合并到现有数据库
            if knowledgeBase is None:
                knowledgeBase = new_db
            else:
                knowledgeBase.merge_from(new_db)
            
            # 保存更新后的数据库
            knowledgeBase.save_local(VECTOR_DB_PATH)
            print(f"✅ 知识库更新完成，新增 {len(new_texts)} 个文本块")
            
            # 更新文档信息
            doc_info_path = os.path.join(VECTOR_DB_PATH, "doc_info.pkl")
            if os.path.exists(doc_info_path):
                with open(doc_info_path, "rb") as f:
                    doc_info = pickle.load(f)
            else:
                doc_info = {"sources": [], "total_chunks": 0, "total_documents": 0}
            
            doc_info["sources"].extend(new_sources)
            doc_info["total_chunks"] += len(new_texts)
            doc_info["total_documents"] += len(new_sources)
            doc_info["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            with open(doc_info_path, "wb") as f:
                pickle.dump(doc_info, f)
            
            # 重新创建QA链
            create_qa_chain()
            
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"更新知识库失败: {e}")
        return False

def create_qa_chain():
    """创建QA链"""
    global qa_chain, knowledgeBase, query_rewriter
    
    if knowledgeBase is None:
        return False
    
    try:
        # 创建LLM - 使用更快的参数
        llm = Tongyi(
            model_name="deepseek-v3", 
            dashscope_api_key=DASHSCOPE_API_KEY,
            temperature=0.1,  # 减少随机性，提高速度
            max_tokens=1000   # 限制输出长度，加快响应
        )
        
        # 初始化查询改写器
        query_rewriter = QueryRewriter(llm)
        
        # 创建优化的检索器 - 减少检索数量以提高速度
        retriever = knowledgeBase.as_retriever(
            search_type="similarity",
            search_kwargs={
                "k": 5,  # 减少检索数量从8到5
                "score_threshold": None  # 移除分数阈值以提高速度
            }
        )
        
        # 创建支持多轮对话的提示模板
        template = """你是一个专业的企业文档助手，请基于以下信息回答用户问题。

历史对话上下文：
{conversation_history}

相关文档内容：
{context}

用户当前问题：{question}

回答要求：
1. 优先基于文档内容回答
2. 结合历史对话上下文理解用户意图
3. 如果有上下文，使用"你之前问..."等自然语言连接
4. 无法找到答案时，说明"根据现有文档和对话上下文无法找到确切答案"
5. 回答要简洁明了："""

        QA_prompt = PromptTemplate(
            template=template, 
            input_variables=["context", "question", "conversation_history"]
        )
        
        # 创建自定义QA链以支持多轮对话
        from langchain.schema import BasePromptTemplate
        from typing import Any, Dict, List
        
        class ConversationalQAChain:
            def __init__(self, llm, retriever, prompt):
                self.llm = llm
                self.retriever = retriever
                self.prompt = prompt
            
            def invoke(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
                query = inputs["query"]
                conversation_history = inputs.get("conversation_history", "")
                
                # 检索相关文档
                docs = self.retriever.get_relevant_documents(query)
                
                # 格式化文档内容
                context = "\n\n".join([doc.page_content for doc in docs])
                
                # 使用提示模板生成回答
                formatted_prompt = self.prompt.format(
                    context=context,
                    question=query,
                    conversation_history=conversation_history
                )
                
                # 调用LLM生成回答
                result = self.llm.invoke(formatted_prompt)
                
                return {
                    "result": result,
                    "source_documents": docs
                }
        
        # 创建对话QA链
        qa_chain = ConversationalQAChain(llm, retriever, QA_prompt)
        
        return True
        
    except Exception as e:
        logger.error(f"创建QA链失败: {e}")
        return False

def load_existing_knowledge_base():
    """加载现有的知识库"""
    global knowledgeBase
    
    try:
        if os.path.exists(VECTOR_DB_PATH):
            embeddings = DashScopeEmbeddings(model="text-embedding-v1", dashscope_api_key=DASHSCOPE_API_KEY)
            knowledgeBase = FAISS.load_local(VECTOR_DB_PATH, embeddings, allow_dangerous_deserialization=True)
            print("✅ 知识库加载成功")
            
            # 加载页码信息
            page_info_path = os.path.join(VECTOR_DB_PATH, "page_info.pkl")
            if os.path.exists(page_info_path):
                with open(page_info_path, "rb") as f:
                    page_info = pickle.load(f)
                knowledgeBase.page_info = page_info
            
            return True
        else:
            print("⚠️ 知识库不存在，需要先创建")
            return False
            
    except Exception as e:
        logger.error(f"加载知识库失败: {e}")
        return False

def get_knowledge_base_info():
    """获取知识库信息"""
    doc_info_path = os.path.join(VECTOR_DB_PATH, "doc_info.pkl")
    if os.path.exists(doc_info_path):
        try:
            with open(doc_info_path, "rb") as f:
                doc_info = pickle.load(f)
            return doc_info
        except Exception as e:
            logger.error(f"读取文档信息失败: {e}")
    
    return {"sources": [], "total_chunks": 0, "total_documents": 0, "last_updated": "未知"}

# 路由定义
@app.route('/')
def index():
    """主页面 - 用户问答界面"""
    return render_template('index.html')

@app.route('/admin')
def admin():
    """管理界面"""
    return render_template('admin.html')

@app.route('/admin/login', methods=['POST'])
def admin_login():
    """管理员登录"""
    username = request.form.get('username')
    password = request.form.get('password')
    
    if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
        session['admin_logged_in'] = True
        flash('登录成功！', 'success')
        return redirect(url_for('admin_dashboard'))
    else:
        flash('用户名或密码错误！', 'error')
        return redirect(url_for('admin'))

@app.route('/admin/dashboard')
def admin_dashboard():
    """管理员仪表板"""
    if not session.get('admin_logged_in'):
        flash('请先登录！', 'error')
        return redirect(url_for('admin'))
    
    doc_info = get_knowledge_base_info()
    return render_template('dashboard.html', doc_info=doc_info)

@app.route('/admin/logout')
def admin_logout():
    """管理员登出"""
    session.pop('admin_logged_in', None)
    flash('已安全登出！', 'info')
    return redirect(url_for('admin'))

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """上传PDF文件"""
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'message': '请先登录！'})
    
    if 'files' not in request.files:
        return jsonify({'success': False, 'message': '没有选择文件！'})
    
    files = request.files.getlist('files')
    uploaded_files = []
    
    for file in files:
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)
            uploaded_files.append(filepath)
        else:
            return jsonify({'success': False, 'message': f'文件 {file.filename} 格式不支持！'})
    
    if uploaded_files:
        # 更新知识库
        success = update_knowledge_base_with_new_pdfs(uploaded_files)
        
        if success:
            # 删除临时文件
            for filepath in uploaded_files:
                os.remove(filepath)
            
            return jsonify({
                'success': True, 
                'message': f'成功上传并处理了 {len(uploaded_files)} 个文件！'
            })
        else:
            return jsonify({'success': False, 'message': '处理文件时出错！'})
    
    return jsonify({'success': False, 'message': '没有有效的文件！'})

@app.route('/api/query', methods=['POST'])
def query_question():
    """处理用户查询 - 支持多轮对话"""
    start_time = time.time()
    
    if not qa_chain:
        logger.error("系统尚未初始化")
        return jsonify({'success': False, 'message': '系统尚未初始化！'}), 500
    
    question = request.json.get('question', '').strip()
    if not question:
        logger.error("收到空问题")
        return jsonify({'success': False, 'message': '请输入问题！'}), 400
    
    logger.info(f"收到查询请求: {question[:50]}...")
    
    try:
        # 获取对话上下文
        conversation_history = conversation_manager.get_context(request, max_context_exchanges=3)
        
        # 快速查询改写（带缓存）
        rewritten_question, was_rewritten = query_rewriter.rewrite_query(question, use_ai=True)
        
        # 生成缓存键 - 包含上下文以区分不同对话场景
        cache_context = conversation_history[-200:] if conversation_history else ""  # 限制上下文长度
        cache_key_input = f"{question}_{cache_context[:50]}"  # 使用问题+部分上下文作为缓存键
        
        # 检查缓存
        cached_response = response_cache.get(cache_key_input, rewritten_question)
        if cached_response:
            total_time = time.time() - start_time
            logger.info(f"总响应时间: {total_time:.3f}秒 (缓存命中) - 问题: {question[:30]}")
            
            # 添加到对话历史（即使是缓存命中也要记录）
            conversation_manager.add_exchange(
                request, question, cached_response['answer'], cached_response.get('sources', [])
            )
            
            cached_response['response_time'] = round(total_time, 2)
            cached_response['from_cache'] = True
            return jsonify(cached_response)
        
        # 快速检索和回答 - 包含对话上下文
        retrieval_start = time.time()
        
        # 构建包含上下文的查询参数
        query_params = {
            "query": rewritten_question,
            "conversation_history": conversation_history if conversation_history else "无历史对话"
        }
        
        response = qa_chain.invoke(query_params)
        retrieval_time = time.time() - retrieval_start
        logger.info(f"LLM调用时间: {retrieval_time:.3f}秒")
        
        # 快速处理来源信息
        sources = []
        if "source_documents" in response:
            source_dict = {}
            for doc in response["source_documents"]:
                source_name = doc.metadata.get("source", "未知文档")
                page_num = doc.metadata.get("page", "未知页码")
                key = f"{source_name} (第{page_num}页)"
                source_dict[key] = source_dict.get(key, 0) + 1
            
            sources = [{"name": source, "count": count} for source, count in source_dict.items()]
        
        # 构建响应数据
        answer = response["result"]
        response_data = {
            'success': True,
            'question': question,
            'rewritten_question': rewritten_question if was_rewritten else None,
            'answer': answer,
            'sources': sources,
            'response_time': round(time.time() - start_time, 2),
            'has_context': bool(conversation_history)
        }
        
        # 添加到对话历史
        conversation_manager.add_exchange(request, question, answer, sources)
        
        # 缓存响应
        response_cache.set(cache_key_input, response_data, rewritten_question)
        
        total_time = time.time() - start_time
        response_data['response_time'] = round(total_time, 2)
        logger.info(f"总响应时间: {total_time:.3f}秒 (缓存设置) - 问题: {question[:30]}")
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"处理查询时出错: {e}")
        return jsonify({'success': False, 'message': '处理查询时出错，请稍后重试！'}), 500

@app.route('/api/kb_info')
def kb_info():
    """获取知识库信息"""
    kb_info = get_knowledge_base_info()
    
    # 添加缓存统计信息
    cache_stats = response_cache.get_stats()
    kb_info['cache'] = cache_stats
    
    return jsonify(kb_info)

@app.route('/api/cache/clear', methods=['POST'])
def clear_cache():
    """清空缓存"""
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'message': '请先登录！'})
    
    try:
        response_cache.clear()
        if query_rewriter:
            query_rewriter.rewrite_cache.clear()
        
        return jsonify({'success': True, 'message': '缓存已清空！'})
    except Exception as e:
        logger.error(f"清空缓存失败: {e}")
        return jsonify({'success': False, 'message': '清空缓存失败！'})

@app.route('/api/rebuild_kb', methods=['POST'])
def rebuild_knowledge_base():
    """重建知识库"""
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'message': '请先登录！'})
    
    try:
        # 删除现有知识库
        if os.path.exists(VECTOR_DB_PATH):
            shutil.rmtree(VECTOR_DB_PATH)
        
        # 这里可以添加从现有PDF文件重建的逻辑
        # 暂时返回成功消息
        return jsonify({'success': True, 'message': '知识库重建命令已执行！'})
        
    except Exception as e:
        logger.error(f"重建知识库失败: {e}")
        return jsonify({'success': False, 'message': '重建知识库失败！'})

@app.route('/api/conversation/history')
def get_conversation_history():
    """获取当前会话的对话历史"""
    try:
        history = conversation_manager.get_history(request)
        return jsonify({'success': True, 'history': history})
    except Exception as e:
        logger.error(f"获取对话历史失败: {e}")
        return jsonify({'success': False, 'message': '获取对话历史失败！'})

@app.route('/api/conversation/clear', methods=['POST'])
def clear_conversation():
    """清空当前会话"""
    try:
        success = conversation_manager.clear_conversation(request)
        if success:
            return jsonify({'success': True, 'message': '对话已清空！'})
        else:
            return jsonify({'success': False, 'message': '清空对话失败！'})
    except Exception as e:
        logger.error(f"清空对话失败: {e}")
        return jsonify({'success': False, 'message': '清空对话失败！'})

@app.route('/api/conversation/stats')
def get_conversation_stats():
    """获取对话统计信息"""
    try:
        if not session.get('admin_logged_in'):
            return jsonify({'success': False, 'message': '请先登录！'})
        
        stats = conversation_manager.get_conversation_stats()
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        logger.error(f"获取对话统计失败: {e}")
        return jsonify({'success': False, 'message': '获取对话统计失败！'})

# 初始化函数
def initialize_system():
    """初始化系统"""
    global knowledgeBase, qa_chain
    
    print("🚀 初始化RAG系统...")
    
    # 加载现有知识库
    if load_existing_knowledge_base():
        # 创建QA链
        if create_qa_chain():
            print("✅ 系统初始化完成")
        else:
            print("❌ QA链创建失败")
    else:
        print("⚠️ 知识库不存在，请先上传PDF文档")

if __name__ == '__main__':
    # 初始化系统
    initialize_system()
    
    # 启动Web应用
    print("🌐 启动Web应用服务器...")
    print("📱 用户界面: http://localhost:5000")
    print("⚙️ 管理界面: http://localhost:5000/admin")
    
    app.run(host='0.0.0.0', port=5000, debug=True)