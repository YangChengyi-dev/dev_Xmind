from flask import Flask, render_template, request, redirect, url_for, flash, send_file
import os
import tempfile
import io
import networkx as nx
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
            # 生成图片
            img_buffer = xmind_to_image(xmind_data)
            
            # 返回图片，支持在线浏览和下载
            return send_file(img_buffer, mimetype='image/png', as_attachment=False,
                           download_name='xmind_map.png')
        else:
            # 生成HTML结构（列表形式）
            html_structure = parse_xmind_structure(xmind_data)
            
            # 渲染结果页面
            return render_template('result.html', structure=html_structure)
    
    except Exception as e:
        flash(f'解析文件时出错: {str(e)}')
        return redirect(url_for('index'))
    
    finally:
        # 清理临时文件
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except:
                pass

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

def xmind_to_image(xmind_data):
    """将XMind数据转换为图片"""
    # 创建图像缓冲区
    img_buffer = io.BytesIO()
    
    # 为每个画布创建一个图像
    images = []
    
    for sheet in xmind_data:
        # 创建网络图
        G = nx.DiGraph()
        pos = {}
        node_labels = {}
        
        # 递归遍历主题，构建网络图
        def traverse_graph(topic, parent=None, node_id=0):
            current_id = node_id
            title = topic.get('title', 'Untitled')
            
            # 添加当前节点
            G.add_node(current_id)
            node_labels[current_id] = title
            
            # 设置节点位置（简化版树状布局）
            if parent is None:
                pos[current_id] = (0, 0)
            else:
                # 计算子节点位置
                children_count = 0
                if 'topics' in topic:
                    if isinstance(topic['topics'], list):
                        children_count = len(topic['topics'])
                    elif isinstance(topic['topics'], dict):
                        for subtopics in topic['topics'].values():
                            children_count += len(subtopics)
                
                # 基于层级和父节点位置设置位置
                level = 1
                p = parent
                while p is not None:
                    level += 1
                    p = [n for n in G.predecessors(p)]
                    p = p[0] if p else None
                
                # 确定水平位置
                x_pos = -level * 2
                y_pos = 0
                
                # 如果有父节点，基于父节点位置调整
                if parent is not None:
                    parent_pos = pos[parent]
                    # 简单的树状布局
                    x_pos = parent_pos[0] - 2
                    # 为了避免节点重叠，使用不同的y位置
                    existing_children = list(G.successors(parent))
                    y_pos = parent_pos[1] - (len(existing_children) * 1.5)
                
                pos[current_id] = (x_pos, y_pos)
                
                # 连接父节点
                if parent is not None:
                    G.add_edge(parent, current_id)
            
            # 处理子主题
            next_id = current_id + 1
            if 'topics' in topic:
                if isinstance(topic['topics'], list):
                    for subtopic in topic['topics']:
                        next_id = traverse_graph(subtopic, current_id, next_id)
                elif isinstance(topic['topics'], dict):
                    for direction, subtopics in topic['topics'].items():
                        for subtopic in subtopics:
                            next_id = traverse_graph(subtopic, current_id, next_id)
            
            return next_id
        
        # 开始构建图
        if 'topic' in sheet:
            traverse_graph(sheet['topic'])
        
        # 创建图像
        plt.figure(figsize=(20, 15))
        
        # 绘制节点和边
        nx.draw_networkx_nodes(G, pos, node_size=3000, node_color='lightblue')
        nx.draw_networkx_edges(G, pos, edge_color='gray', arrows=True)
        nx.draw_networkx_labels(G, pos, node_labels, font_size=10, font_family='SimHei')
        
        # 设置标题
        plt.title(sheet.get('title', 'Untitled Sheet'), fontsize=16, fontfamily='SimHei')
        plt.axis('off')
        plt.tight_layout()
        
        # 保存到临时缓冲区
        canvas = FigureCanvas(plt.gcf())
        canvas.draw()
        
        # 将matplotlib图形转换为PIL图像
        pil_image = Image.frombytes('RGB', canvas.get_width_height(), canvas.tostring_rgb())
        images.append(pil_image)
        
        # 清除当前图形
        plt.close()
    
    # 如果有多个画布，将它们合并
    if images:
        if len(images) == 1:
            # 单个画布直接保存
            images[0].save(img_buffer, format='PNG')
        else:
            # 多个画布，计算总高度
            total_width = max(img.width for img in images)
            total_height = sum(img.height for img in images)
            
            # 创建新图像
            combined = Image.new('RGB', (total_width, total_height), color='white')
            
            # 粘贴所有图像
            y_offset = 0
            for img in images:
                combined.paste(img, ((total_width - img.width) // 2, y_offset))
                y_offset += img.height
            
            # 保存合并后的图像
            combined.save(img_buffer, format='PNG')
    
    img_buffer.seek(0)
    return img_buffer

# 错误处理
@app.errorhandler(413)
def request_entity_too_large(error):
    flash('文件太大，最大支持100MB')
    return redirect(url_for('index'))

if __name__ == '__main__':
    # 避免使用5000和5001端口，使用5002端口
    app.run(debug=True, port=5002, host='0.0.0.0')