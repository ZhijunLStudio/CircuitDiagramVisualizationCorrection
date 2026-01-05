import gradio as gr
import requests
import json
import base64

# ================= 配置区 =================
NICEGUI_HOST = "http://localhost:8060" 
# =========================================

def init_session_api(image, json_input):
    """
    1. 发送数据创建会话
    2. 返回 session_id, 状态信息, HTML链接, 以及 **激活定时器**
    """
    if image is None or not json_input:
        return None, "⚠️ 请先上传图片和JSON", None, gr.Timer(active=False)
    
    # 图片转 Base64
    try:
        with open(image, "rb") as f:
            img_b64 = "data:image/png;base64," + base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        return None, f"❌ 图片读取失败: {e}", None, gr.Timer(active=False)

    payload = {
        "image_b64": img_b64,
        "json_str": json_input
    }
    
    try:
        # 请求 NiceGUI 服务
        response = requests.post(f"{NICEGUI_HOST}/api/init_session", json=payload)
        
        if response.status_code != 200:
            return None, f"❌ 服务端错误: {response.text}", None, gr.Timer(active=False)
            
        res_data = response.json()
        session_id = res_data["session_id"]
        target_url = f"{NICEGUI_HOST}/edit/{session_id}"
        
        # 生成备用跳转链接
        html_link = f"""
        <div style="text-align: center; padding: 10px; background-color: #e6fffa; border: 1px solid #38b2ac; border-radius: 5px;">
            <a href="{target_url}" target="_blank" style="font-size: 16px; font-weight: bold; color: #2c7a7b; text-decoration: none;">
                👉 如果未自动弹出，请点击这里进入标注页面
            </a>
        </div>
        """
        
        # 关键：返回 gr.Timer(active=True) 启动轮询
        return session_id, "⏳ 会话已建立，正在等待标注结果...", html_link, gr.Timer(active=True, value=1)
        
    except Exception as e:
        return None, f"❌ 连接失败 (检查 viz_server.py 是否运行): {e}", None, gr.Timer(active=False)

def check_result_api(session_id):
    """
    轮询函数：
    - 如果拿到结果：更新 JSON，并关闭定时器。
    - 如果还在做：保持定时器开启。
    """
    if not session_id:
        return gr.update(), "等待开始...", gr.Timer(active=False)
    
    try:
        res = requests.get(f"{NICEGUI_HOST}/api/get_result", params={"session_id": session_id})
        data = res.json()
        
        if data["status"] == "done":
            # ✅ 成功拿到结果
            new_json = json.dumps(json.loads(data["json"]), indent=2, ensure_ascii=False)
            # 更新 JSON 内容，更新状态，**关闭定时器**
            return new_json, "✅ 标注完成！结果已更新。", gr.Timer(active=False)
        
        elif data["status"] == "error":
            return gr.update(), f"❌ 错误: {data.get('msg')}", gr.Timer(active=False)
        
        else:
            # ⏳ 还在标注中，保持定时器开启
            return gr.update(), "⏳ 正在 NiceGUI 中标注... (请在弹出的页面点击保存)", gr.Timer(active=True)
            
    except Exception as e:
        return gr.update(), f"❌ 轮询错误: {e}", gr.Timer(active=False)

# --- Gradio 界面 ---

with gr.Blocks(title="电路图修正系统", theme=gr.themes.Soft()) as demo:
    gr.Markdown("## ⚡️ 电路图智能解析与修正系统")
    
    state_session_id = gr.State("")

    with gr.Row():
        # 左侧
        with gr.Column(scale=1):
            img_input = gr.Image(type="filepath", label="1. 上传图片", height=300)
            default_json = json.dumps({"components": {"R1": {"type": "Res", "box": [50,50,150,150], "ports": []}},"connections": [], "external_ports": {}}, indent=2)
            json_input = gr.Code(value=default_json, language="json", label="2. JSON 数据")
            
            btn_annotate = gr.Button("🎨 开始标注", variant="primary", size="lg")
            
            link_output = gr.HTML() # 跳转链接显示区
            status_box = gr.Textbox(label="系统状态", interactive=False)
            
        # 右侧
        with gr.Column(scale=1):
            # 结果显示区
            result_output = gr.Code(language="json", label="3. 修正后的结果 (自动刷新)", lines=25)

    # 定时器 (初始状态为关闭)
    timer = gr.Timer(active=False)

    # --- 交互逻辑 ---

    # 1. 点击按钮 -> 发送请求 -> 启动定时器 -> 触发 JS 跳转
    btn_annotate.click(
        fn=init_session_api,
        inputs=[img_input, json_input],
        outputs=[state_session_id, status_box, link_output, timer] # 更新 timer 状态为 active=True
    ).then(
        fn=None,
        inputs=[state_session_id],
        js=f"(s) => {{ if(s) window.open('{NICEGUI_HOST}/edit/' + s, '_blank'); }}", # JS 自动跳转
    )

    # 2. 定时器每秒触发一次 check_result_api
    # check_result_api 会返回新的 JSON 和 新的 Timer 状态 (完成时设为 False)
    timer.tick(
        fn=check_result_api,
        inputs=[state_session_id],
        outputs=[result_output, status_box, timer]
    )

if __name__ == "__main__":
    demo.launch(server_port=7863, show_error=True)