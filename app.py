import os
import cv2
import numpy as np
from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from werkzeug.utils import secure_filename
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import subprocess
import platform

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'outputs'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg'}
app.config['MAX_PHOTOS'] = 10  # 最大照片数量

# 确保上传和输出目录存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def create_black_image(width, height):
    """创建黑色背景图像"""
    return np.zeros((height, width, 3), dtype=np.uint8)

def get_chinese_font(font_size):
    """获取中文字体，支持跨平台"""
    system = platform.system()
    
    # 尝试不同平台的中文字体路径
    font_paths = [
        # Windows
        "C:/Windows/Fonts/simhei.ttf",  # 黑体
        "C:/Windows/Fonts/msyh.ttc",    # 微软雅黑
        
        # Linux
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
        
        # macOS
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    
    # 尝试加载可用字体
    for path in font_paths:
        try:
            return ImageFont.truetype(path, font_size)
        except:
            continue
    
    # 如果都找不到，尝试默认字体（可能不支持中文）
    try:
        return ImageFont.truetype("Arial", font_size)
    except:
        return ImageFont.load_default()

def add_caption_to_image(image_path, caption, output_path, font_size_percent=5, vertical_position_percent=90):
    """
    在图像上添加字幕（使用中文字体）
    :param font_size_percent: 字体大小占图片高度的百分比
    :param vertical_position_percent: 字幕垂直位置（0-100，0=顶部，100=底部）
    """
    # 打开图像
    img = Image.open(image_path)
    draw = ImageDraw.Draw(img)
    
    # 获取图像尺寸
    width, height = img.size
    
    # 计算实际字体大小
    font_size = int(height * font_size_percent / 100)
    
    # 获取中文字体
    font = get_chinese_font(font_size)
    
    # 计算文本位置 - 使用新的textbbox方法
    bbox = draw.textbbox((0, 0), caption, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    # 计算垂直位置
    # vertical_position_percent: 0=顶部, 100=底部
    y_position = height * vertical_position_percent / 100 - text_height / 2
    
    # 确保位置在图像范围内
    y_position = max(20, min(height - text_height - 20, y_position))
    
    position = ((width - text_width) // 2, int(y_position))
    
    # 添加黑色背景框增强可读性
    padding = 5
    draw.rectangle(
        [position[0] - padding, position[1] - padding, 
         position[0] + text_width + padding, position[1] + text_height + padding],
        fill="black"
    )
    
    # 添加文本
    draw.text(position, caption, font=font, fill="white")
    
    # 保存结果
    img.save(output_path)

def create_video_from_images(image_paths, captions, output_path, 
                            global_font_size=5, global_vertical_position=90,
                            photo_duration=3, fps=24):
    """从图像列表创建视频"""
    # 处理每张图片并添加字幕
    processed_images = []
    for i, img_path in enumerate(image_paths):
        # 如果图片不存在，创建黑色背景
        if img_path is None:
            # 尝试获取其他图片的尺寸作为参考
            if processed_images:
                ref_img = cv2.imread(processed_images[0])
                height, width, _ = ref_img.shape
            else:
                width, height = 1280, 720  # 默认尺寸
            black_img = create_black_image(width, height)
            temp_path = os.path.join(app.config['UPLOAD_FOLDER'], f"black_{i}.png")
            cv2.imwrite(temp_path, black_img)
            img_path = temp_path
        
        # 添加字幕
        caption = captions[i] if i < len(captions) else ""
        temp_output = os.path.join(app.config['UPLOAD_FOLDER'], f"captioned_{i}.png")
        
        # 使用全局设置添加字幕
        add_caption_to_image(
            img_path, 
            caption, 
            temp_output,
            font_size_percent=global_font_size,
            vertical_position_percent=global_vertical_position
        )
        processed_images.append(temp_output)
    
    # 读取第一张图片以获取尺寸
    frame = cv2.imread(processed_images[0])
    height, width, _ = frame.shape
    
    # 创建视频写入器
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    video = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
    
    # 计算每张图片的帧数
    frames_per_image = int(photo_duration * fps)
    
    # 将每张图片写入视频
    for img_path in processed_images:
        img = cv2.imread(img_path)
        for _ in range(frames_per_image):
            video.write(img)
    
    # 清理并释放视频写入器
    video.release()
    
    # 清理临时文件
    for img_path in processed_images:
        if img_path.startswith(os.path.join(app.config['UPLOAD_FOLDER'], "black_")) or \
           img_path.startswith(os.path.join(app.config['UPLOAD_FOLDER'], "captioned_")):
            os.remove(img_path)
    
    # 使用FFmpeg重新编码以获得更好的兼容性
    if is_ffmpeg_available():
        temp_output = output_path.replace('.mp4', '_temp.mp4')
        os.rename(output_path, temp_output)
        ffmpeg_cmd = [
            'ffmpeg', '-i', temp_output, 
            '-c:v', 'libx264', '-preset', 'slow', '-crf', '22',
            '-pix_fmt', 'yuv420p', output_path
        ]
        subprocess.run(ffmpeg_cmd, check=True)
        os.remove(temp_output)

def is_ffmpeg_available():
    """检查系统是否安装了FFmpeg"""
    try:
        subprocess.run(['ffmpeg', '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False

@app.route('/')
def index():
    """主页面"""
    return render_template('index.html', max_photos=app.config['MAX_PHOTOS'])

@app.route('/upload', methods=['POST'])
def upload():
    """处理上传和生成视频"""
    # 创建时间戳作为输出文件名
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    output_filename = f"video_{timestamp}.mp4"
    output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
    
    # 获取全局设置
    try:
        global_font_size = float(request.form.get('global_font_size', 5))
        global_vertical_position = float(request.form.get('global_vertical_position', 90))
        photo_duration = float(request.form.get('photo_duration', 3))
    except ValueError as e:
        print(f"参数转换错误: {e}")
        return "参数格式错误"
    
    # 调试信息 - 确保获取到正确的设置值
    print(f"用户设置: 字体大小={global_font_size}%, 位置={global_vertical_position}%, 显示时间={photo_duration}秒")
    
    # 收集上传的文件和字幕
    images = []
    captions = []
    
    # 获取照片数量
    photo_count = int(request.form.get('photo_count', 2))
    
    # 处理每张照片
    for i in range(1, photo_count + 1):
        file_key = f'photo_{i}'
        caption_key = f'caption_{i}'
        
        # 获取字幕
        caption = request.form.get(caption_key, '')
        captions.append(caption)
        
        # 获取上传的文件
        file = request.files.get(file_key)
        if file and file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(f"{timestamp}_{i}_{file.filename}")
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            images.append(file_path)
        else:
            images.append(None)
    
    # 创建视频
    create_video_from_images(
        images, 
        captions, 
        output_path,
        global_font_size=global_font_size,
        global_vertical_position=global_vertical_position,
        photo_duration=photo_duration
    )
    
    return redirect(url_for('result', filename=output_filename))

@app.route('/result/<filename>')
def result(filename):
    """显示结果页面并提供下载链接"""
    return render_template('result.html', filename=filename)

@app.route('/download/<filename>')
def download(filename):
    """提供视频下载"""
    return send_from_directory(app.config['OUTPUT_FOLDER'], filename, as_attachment=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
