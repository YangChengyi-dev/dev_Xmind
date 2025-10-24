from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session
import os
import tempfile
import io
import networkx as nx
# 配置Matplotlib使用非交互式后端，避免线程安全问题
import matplotlib
matplotlib.use('Agg')  # 使用Agg后端，非交互式
import matplotlib.pyplot as plt
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
from PIL import Image
from xmindparser import xmind_to_dict

# 设置中文显示
plt.rcParams['font.sans-serif'] = ['SimHei']  # 用来正常显示中文标签
plt.rcParams['axes.unicode_minus'] = False    # 用来正常显示负号

# 创建Flask应用
app = Flask(__name__)
app.secret_key = 'your-secret-key'
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB 限制
# 增加session存储时间以保存解析数据
app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 1小时

# 确保上传文件夹存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# 允许的文件扩展名
ALLOWED_EXTENSIONS = {'xmind'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def is_xmind_file(file_path):
    """检查文件是否为有效的XMind文件"""
    try:
        # 直接尝试解析文件来验证
        xmind_to_dict(file_path)
        return True
    except:
        return False

# 后续已定义优化版本的parse_xmind_structure函数

# 主页面
@app.route('/')
def index():
    return render_template('index.html')

# 文件上传和解析路由
@app.route('/upload', methods=['POST'])
def upload_file():
    # 检查是否有文件部分
    if 'file' not in request.files:
        flash('没有文件部分')
        return redirect(url_for('index'))
    
    file = request.files['file']
    
    # 检查用户是否选择了文件
    if file.filename == '':
        flash('未选择文件')
        return redirect(url_for('index'))
    
    # 检查文件扩展名
    if not allowed_file(file.filename):
        flash('无效的文件类型，仅支持.xmind文件')
        return redirect(url_for('index'))
    
    # 保存文件到临时位置
    temp_file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
    file.save(temp_file_path)
    
    try:
        # 验证是否为有效XMind文件
        if not is_xmind_file(temp_file_path):
            flash('无效的XMind文件')
            return redirect(url_for('index'))
        
        # 获取解析模式
        parse_mode = request.form.get('parse_mode', 'list')
        
        # 解析XMind文件
        xmind_data = xmind_to_dict(temp_file_path)
        
        if parse_mode == 'image':
            # 为解析后的数据创建一个唯一的临时文件路径
            import uuid
            session_id = str(uuid.uuid4())
            data_file_path = os.path.join(app.config['UPLOAD_FOLDER'], f'xmind_data_{session_id}.json')
            
            # 将解析后的数据保存到临时文件中（使用JSON格式）
            import json
            with open(data_file_path, 'w', encoding='utf-8') as f:
                # 自定义序列化函数处理复杂对象
                def custom_serializer(obj):
                    if isinstance(obj, bytes):
                        return obj.decode('utf-8', errors='replace')
                    raise TypeError(f'Object of type {type(obj).__name__} is not JSON serializable')
                
                # 保存为JSON字符串
                json.dump(xmind_data, f, ensure_ascii=False, default=custom_serializer)
            
            # 开启session，只保存必要信息
            session.permanent = True
            session['data_file_path'] = data_file_path
            session['filename'] = file.filename
            
            # 提取画布信息（只保存必要的元数据）
            sheets_info = []
            for i, sheet in enumerate(xmind_data):
                sheets_info.append({
                    'id': i,
                    'title': sheet.get('title', f'画布 {i+1}')
                })
            
            # 保存画布信息，标记解析为已完成
            session['sheets_info'] = sheets_info
            session['parsing_completed'] = True  # 对于36M这样的大文件，解析已经在xmind_to_dict完成
            
            # 获取文件大小，用于前端提示
            import time
            file_size = os.path.getsize(temp_file_path) / (1024 * 1024)  # MB
            
            # 渲染画布选择页面，为所有文件返回模板
            return render_template('image_result.html', 
                                 sheets=sheets_info,
                                 current_sheet=0,
                                 filename=file.filename,
                                 parsing_completed=True,
                                 file_size=file_size)
        else:
            # 生成HTML结构（列表形式）
            html_structure = parse_xmind_structure(xmind_data)
            
            # 渲染结果页面
            return render_template('result.html', structure=html_structure)
    
    except Exception as e:
        flash(f'解析文件时出错: {str(e)}')
        return redirect(url_for('index'))
    
    finally:
        # 清理原始临时文件，但保留解析后的数据文件
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except:
                pass

# 获取特定画布的图片路由
@app.route('/get_sheet_image/<int:sheet_id>')
def get_sheet_image(sheet_id):
    # 检查session中是否有解析数据文件路径
    if 'data_file_path' not in session or 'sheets_info' not in session:
        flash('没有找到解析数据，请重新上传文件')
        return redirect(url_for('index'))
    
    data_file_path = session['data_file_path']
    sheets_info = session['sheets_info']
    
    # 检查画布ID是否有效
    if sheet_id < 0 or sheet_id >= len(sheets_info):
        flash('无效的画布ID')
        return redirect(url_for('index'))
    
    try:
        # 从临时文件加载解析后的数据
        import json
        with open(data_file_path, 'r', encoding='utf-8') as f:
            xmind_data = json.load(f)
        
        # 生成指定画布的图片
        sheet_data = xmind_data[sheet_id]
        img_buffer = generate_sheet_image(sheet_data)
        
        # 返回图片
        return send_file(img_buffer, mimetype='image/png', as_attachment=False,
                       download_name=f'sheet_{sheet_id}.png')
    
    except Exception as e:
        flash(f'生成图片时出错: {str(e)}')
        return redirect(url_for('index'))

# 下载特定画布的图片路由
@app.route('/download_sheet_image/<int:sheet_id>')
def download_sheet_image(sheet_id):
    # 检查session中是否有解析数据文件路径
    if 'data_file_path' not in session or 'sheets_info' not in session:
        flash('没有找到解析数据，请重新上传文件')
        return redirect(url_for('index'))
    
    data_file_path = session['data_file_path']
    sheets_info = session['sheets_info']
    
    # 检查画布ID是否有效
    if sheet_id < 0 or sheet_id >= len(sheets_info):
        flash('无效的画布ID')
        return redirect(url_for('index'))
    
    try:
        # 从临时文件加载解析后的数据
        import json
        with open(data_file_path, 'r', encoding='utf-8') as f:
            xmind_data = json.load(f)
        
        # 生成指定画布的图片
        sheet_data = xmind_data[sheet_id]
        sheet_title = sheet_data.get('title', f'sheet_{sheet_id}')
        img_buffer = generate_sheet_image(sheet_data)
        
        # 下载图片
        return send_file(img_buffer, mimetype='image/png', as_attachment=True,
                       download_name=f'{sheet_title}.png')
    
    except Exception as e:
        flash(f'生成图片时出错: {str(e)}')
        return redirect(url_for('index'))

# 优化解析大文件的函数
def parse_xmind_structure(xmind_data):
    """高效地将XMind数据转换为HTML友好的结构"""
    html_structure = []
    
    def traverse_topic(topic, level=0):
        # 使用列表收集并一次性join，避免频繁字符串拼接
        parts = []
        parts.append(f"<div class='topic level-{level}'>")
        parts.append(f"  <div class='topic-content'>{topic.get('title', 'Untitled')}</div>")
        
        if 'topics' in topic:
            parts.append(f"  <div class='subtopics'>")
            if isinstance(topic['topics'], list):
                for subtopic in topic['topics']:
                    parts.extend(traverse_topic(subtopic, level + 1))
            elif isinstance(topic['topics'], dict):
                for direction, subtopics in topic['topics'].items():
                    for subtopic in subtopics:
                        parts.extend(traverse_topic(subtopic, level + 1))
            parts.append(f"  </div>")
        
        parts.append(f"</div>")
        return parts
    
    # 处理所有画布
    for sheet in xmind_data:
        html_structure.append(f"<div class='sheet'>")
        html_structure.append(f"  <h2>{sheet.get('title', 'Untitled Sheet')}</h2>")
        
        if 'topic' in sheet:
            root_topic = sheet['topic']
            html_structure.extend(traverse_topic(root_topic, 0))
        
        html_structure.append(f"</div>")
    
    return '\n'.join(html_structure)

def generate_sheet_image(sheet_data):
    """为单个画布生成更清晰的图像（使用非交互式后端，避免线程安全问题）"""
    # 创建图片缓冲区
    buffer = io.BytesIO()
    
    try:
        # 创建更高级的网络图布局
        G = nx.DiGraph()
        node_labels = {}
        
        # 递归遍历主题，构建网络图和节点属性
        def traverse_graph(topic, parent=None, node_id=0, level=0):
            current_id = node_id
            title = topic.get('title', 'Untitled')
            
            # 添加当前节点和属性
            G.add_node(current_id, title=title, level=level)
            node_labels[current_id] = title
            
            # 连接父节点
            if parent is not None:
                G.add_edge(parent, current_id)
            
            # 处理子主题
            next_id = current_id + 1
            child_count = 0
            
            if 'topics' in topic:
                if isinstance(topic['topics'], list):
                    for subtopic in topic['topics']:
                        next_id = traverse_graph(subtopic, current_id, next_id, level + 1)
                        child_count += 1
                elif isinstance(topic['topics'], dict):
                    for direction, subtopics in topic['topics'].items():
                        for subtopic in subtopics:
                            next_id = traverse_graph(subtopic, current_id, next_id, level + 1)
                            child_count += 1
            
            # 返回更新后的ID和子节点数量
            return next_id
        
        # 开始构建图
        if 'topic' in sheet_data:
            traverse_graph(sheet_data['topic'])
        
        # 创建图像
        plt.figure(figsize=(24, 18))
        
        # 设置字体支持中文，使用多种回退字体
        plt.rcParams['font.sans-serif'] = ['SimHei', 'WenQuanYi Micro Hei', 'Heiti TC']
        plt.rcParams['axes.unicode_minus'] = False
        
        # 使用更智能的布局算法
        # 计算节点层次
        levels = {n: d['level'] for n, d in G.nodes(data=True)}
        
        # 创建基于层次的位置布局
        pos = {}
        # 根节点居中放置
        root_nodes = [n for n, d in G.in_degree() if d == 0]
        if root_nodes:
            root = root_nodes[0]
            pos[root] = (0, 0)
            
            # 为每个层次安排位置
            level_nodes = {0: [root]}
            for level in range(max(levels.values()) + 1):
                if level not in level_nodes:
                    continue
                    
                for node in level_nodes[level]:
                    children = list(G.successors(node))
                    child_count = len(children)
                    
                    if child_count > 0:
                        # 为子节点分配位置，避免重叠
                        if level not in level_nodes:
                            level_nodes[level] = []
                        
                        level_nodes[level + 1] = level_nodes.get(level + 1, []) + children
                        
                        # 计算子节点的垂直间距
                        if child_count == 1:
                            # 只有一个子节点，居中
                            pos[children[0]] = (pos[node][0] - 3, pos[node][1])
                        else:
                            # 多个子节点，均匀分布
                            spacing = min(8, child_count * 1.5)  # 根据子节点数量调整间距
                            start_y = pos[node][1] - (spacing / 2)
                            
                            for i, child in enumerate(children):
                                pos[child] = (pos[node][0] - 3, start_y + (spacing / (child_count - 1) * i) if child_count > 1 else start_y)
        
        # 如果pos为空，使用spring布局作为备选
        if not pos:
            pos = nx.spring_layout(G, seed=42, k=0.3, iterations=100)
        
        # 为不同层级的节点设置不同颜色
        node_colors = []
        for n, d in G.nodes(data=True):
            level = d.get('level', 0)
            # 使用层次相关的颜色
            colors = ['#FFD700', '#98FB98', '#87CEFA', '#DDA0DD', '#FFA07A', '#F0E68C']
            color_idx = min(level, len(colors) - 1)
            node_colors.append(colors[color_idx])
        
        # 调整节点大小
        node_sizes = [2500 + len(label) * 50 for label in node_labels.values()]
        
        # 绘制节点
        nx.draw_networkx_nodes(G, pos, node_size=node_sizes, node_color=node_colors, alpha=0.9, edgecolors='gray')
        
        # 绘制边，使用不同宽度
        nx.draw_networkx_edges(G, pos, edge_color='gray', width=1.5, arrows=True, arrowsize=20)
        
        # 绘制标签，调整字体大小
        font_sizes = [min(12, max(8, 120 / (len(label) + 1))) for label in node_labels.values()]
        
        # 单独绘制每个标签以控制字体大小
        for node, label in node_labels.items():
            size = min(12, max(8, 120 / (len(label) + 1)))
            nx.draw_networkx_labels(G.subgraph([node]), pos, {node: label}, font_size=size, font_family='SimHei', font_weight='bold')
        
        # 设置标题
        plt.title(sheet_data.get('title', 'Untitled Sheet'), fontsize=20, fontfamily='SimHei', pad=20)
        plt.axis('off')
        plt.tight_layout()
        
        # 保存到缓冲区
        plt.savefig(buffer, format='png', dpi=100, bbox_inches='tight', facecolor='white')
        buffer.seek(0)
        
    except Exception as e:
        # 捕获所有异常，确保plt.close()执行
        print(f"生成图片时出错: {str(e)}")
    finally:
        # 清理当前图形，避免内存泄漏
        plt.close('all')  # 关闭所有图形，更彻底的清理
    
    return buffer

def xmind_to_image(xmind_data):
    """将XMind数据转换为图片（主画布）"""
    if not xmind_data:
        return None
    
    # 默认使用第一个画布（主画布）
    main_sheet = xmind_data[0]
    return generate_sheet_image(main_sheet)

# 清理临时数据文件的函数
def cleanup_temp_files():
    """清理过期的临时数据文件"""
    try:
        import time
        current_time = time.time()
        # 清理超过2小时的文件
        max_age = 2 * 3600
        
        for filename in os.listdir(app.config['UPLOAD_FOLDER']):
            if filename.startswith('xmind_data_') and filename.endswith('.json'):
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                if os.path.exists(file_path):
                    file_age = current_time - os.path.getmtime(file_path)
                    if file_age > max_age:
                        try:
                            os.remove(file_path)
                        except:
                            pass
    except:
        # 忽略清理过程中的错误
        pass

# 每次请求后尝试清理过期文件和管理缓存
@app.after_request
def after_request(response):
    # 异步清理临时文件，避免阻塞响应
    import threading
    threading.Thread(target=cleanup_temp_files).start()
    
    # 限制缓存大小，避免内存占用过大
    if 'image_cache' in globals():
        max_cache_size = 10  # 最多缓存10张图片
        if len(image_cache) > max_cache_size:
            # 删除最早添加的缓存项
            first_key = next(iter(image_cache))
            del image_cache[first_key]
    return response

# 错误处理
@app.errorhandler(413)
def request_entity_too_large(error):
    flash('文件太大，最大支持100MB')
    return redirect(url_for('index'))

@app.errorhandler(404)
def not_found_error(error):
    flash('请求的页面不存在')
    return redirect(url_for('index'))

@app.errorhandler(500)
def internal_server_error(error):
    flash('服务器内部错误，请稍后再试')
    return redirect(url_for('index'))

@app.errorhandler(Exception)
def general_exception_handler(error):
    # 捕获其他未明确处理的异常
    flash(f'处理请求时出错: {str(error)}')
    return redirect(url_for('index'))

if __name__ == '__main__':
    # 避免使用5000和5001端口，使用5002端口
    app.run(debug=True, port=5002, host='0.0.0.0')