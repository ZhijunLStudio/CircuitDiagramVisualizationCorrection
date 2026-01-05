from nicegui import ui, app, events
from fastapi import Request
import uuid
import json
import base64
import io
from PIL import Image  # 必须安装 pillow
from viz_core import SystemBlockViz

# ==========================================
# 1. 全局内存数据库
# ==========================================
SESSIONS = {}

# ==========================================
# 2. API 接口
# ==========================================

@app.post("/api/init_session")
async def init_session(request: Request):
    data = await request.json()
    img_b64 = data.get("image_b64")
    json_str = data.get("json_str")
    
    session_id = str(uuid.uuid4())
    
    # 解析图片真实尺寸
    try:
        if "," in img_b64:
            header, encoded = img_b64.split(",", 1)
        else:
            encoded = img_b64
        
        img_data = base64.b64decode(encoded)
        img_obj = Image.open(io.BytesIO(img_data))
        width, height = img_obj.size
    except Exception as e:
        print(f"Image parse error: {e}")
        width, height = 1000, 1000 # 兜底尺寸

    try:
        viz_obj = SystemBlockViz(json_str)
    except Exception as e:
        return {"status": "error", "msg": f"JSON Parse Error: {str(e)}"}

    SESSIONS[session_id] = {
        "viz": viz_obj,
        "img_src": img_b64,
        "img_size": (width, height), # 存入真实尺寸
        "result": None,
        "done": False
    }
    
    return {"session_id": session_id, "url": f"/edit/{session_id}"}

@app.get("/api/get_result")
def get_result(session_id: str):
    if session_id not in SESSIONS:
        return {"status": "error", "msg": "Session not found"}
    
    session = SESSIONS[session_id]
    if session["done"]:
        return {"status": "done", "json": session["result"]}
    else:
        return {"status": "pending"}

# ==========================================
# 3. 标注页面逻辑
# ==========================================

@ui.page('/edit/{session_id}')
def edit_page(session_id: str):
    if session_id not in SESSIONS:
        ui.label("Session expired or invalid").classes("text-red-500 text-2xl m-10")
        return

    # 加载会话数据
    session_data = SESSIONS[session_id]
    viz_instance = session_data["viz"]
    img_src = session_data["img_src"]
    img_w, img_h = session_data["img_size"] # 获取真实尺寸
    
    # 局部状态管理
    state = {
        "viz": viz_instance,
        "mode": "VIEW",
        "selected": None,
        "temp_draw": None,
        "connect_start": None,
        "history": [],
        "zoom": 1.0,
        "ui": {
            "img": None, 
            "info_panel": None, 
            "mode_btns": {}, 
            "undo_btn": None,
            "status": None
        }
    }

    # --- 撤销/重做 ---
    def save_history():
        state["history"].append(state["viz"].clone_data())
        if len(state["history"]) > 20: state["history"].pop(0)
        if state["ui"]["undo_btn"]: state["ui"]["undo_btn"].enable()

    def undo():
        if not state["history"]: return
        prev_data = state["history"].pop()
        state["viz"].restore_data(prev_data)
        state["selected"] = None
        if not state["history"] and state["ui"]["undo_btn"]: 
            state["ui"]["undo_btn"].disable()
        update_info_panel(None)
        refresh_canvas()
        ui.notify("已撤销")

    # --- 缩放 ---
    def set_zoom(val):
        state["zoom"] = val
        if state["ui"]["img"]:
            state["ui"]["img"].style(f'transform: scale({val}); transform-origin: top left;')

    def zoom_in(): set_zoom(min(state["zoom"] + 0.1, 3.0))
    def zoom_out(): set_zoom(max(state["zoom"] - 0.1, 0.2))
    def zoom_reset(): set_zoom(1.0)

    # --- 模式切换 ---
    def set_mode(mode):
        state["mode"] = mode
        state["selected"] = None
        state["connect_start"] = None
        state["temp_draw"] = None
        
        for k, btn in state["ui"]["mode_btns"].items():
            if k == mode: btn.props('color=primary')
            else: btn.props('color=white text-color=black') 
        
        tips = {
            'VIEW': '【查看/编辑】点击对象选中。选组件/端口高亮网络；选连线高亮单根。',
            'ADD_COMP': '【画框模式】拖拽画框创建组件。',
            'ADD_PORT': '【端口模式】点击添加端口。',
            'CONNECT': '【连线模式】点击端口A -> 端口B。'
        }
        if state["ui"]["status"]: state["ui"]["status"].set_text(tips.get(mode, ''))
        update_info_panel(None)
        refresh_canvas()

    # --- 删除逻辑 ---
    def delete_selection():
        save_history()
        sel = state["selected"]
        viz = state["viz"]
        if not sel: return

        if sel["type"] == "component": viz.delete_component(sel["name"])
        elif sel["type"] == "port": viz.delete_port(sel["comp"], sel["port"])
        elif sel["type"] == "conn_center": viz.delete_connection_node(sel["index"], None)
        elif sel["type"] == "conn_edge": viz.delete_connection_node(sel["index"], sel["node"])
        
        ui.notify("已删除")
        state["selected"] = None
        update_info_panel(None)
        refresh_canvas()

    # --- 属性修改回调 ---
    def on_component_rename(new_val):
        sel = state["selected"]
        if not sel or sel["name"] == new_val: return
        save_history()
        success, msg = state["viz"].rename_component(sel["name"], new_val)
        if success: 
            sel["name"] = new_val; ui.notify("重命名成功"); refresh_canvas()
        else: ui.notify(msg, color='negative')

    def on_component_type_change(new_val):
        sel = state["selected"]
        if not sel: return
        save_history()
        state["viz"].update_component_type(sel["name"], new_val)

    def on_port_rename(new_val):
        sel = state["selected"]
        if not sel or sel["port"] == new_val: return
        save_history()
        success, msg = state["viz"].rename_port(sel["comp"], sel["port"], new_val)
        if success: 
            sel["port"] = new_val; ui.notify("重命名成功"); refresh_canvas()
        else: ui.notify(msg, color='negative')

    # --- 左侧面板更新 ---
    def update_info_panel(hit):
        panel = state["ui"]["info_panel"]
        if not panel: return
        panel.clear()
        
        if not hit:
            with panel: ui.label("未选中对象").classes('text-gray-400 italic')
            return
        
        viz = state["viz"]
        with panel:
            ui.label('属性编辑').classes('font-bold text-gray-700 mb-2')
            
            if hit["type"] == "component":
                ui.input('名称', value=hit["name"], on_change=lambda e: on_component_rename(e.value)).classes('w-full')
                curr_type = viz.data["components"][hit["name"]].get("type", "")
                ui.input('类型', value=curr_type, on_change=lambda e: on_component_type_change(e.value)).classes('w-full')
            
            elif hit["type"] == "port":
                ui.input('名称', value=hit["port"], on_change=lambda e: on_port_rename(e.value)).classes('w-full')
                ui.label(f"所属: {hit['comp']}").classes('text-sm text-gray-600 mt-2')

            elif hit["type"] == "conn_center":
                ui.label("连接网络").classes('text-lg text-green-700 font-bold')
                ui.button('删除整个网络', on_click=delete_selection, color='red').classes('w-full mt-2')
                return

            elif hit["type"] == "conn_edge":
                ui.label("连线分支").classes('text-lg text-green-600 font-bold')
                node = hit["node"]
                ui.label(f"{node['component']} -> {node['port']}").classes('text-sm text-gray-700 my-2')
                ui.button('断开此连线', on_click=delete_selection, color='orange').classes('w-full mt-2')
                return

            ui.separator().classes('my-4')
            ui.button('删除', on_click=delete_selection, color='red', icon='delete').classes('w-full')

    # --- 绘图核心 ---
    def refresh_canvas(draw_only_temp=False):
        img_comp = state["ui"]["img"]
        if not img_comp: return
        
        # 使用真实解析出的尺寸设置 viewBox
        w, h = img_w, img_h
        
        svg_content = ""
        
        if not draw_only_temp:
            viz = state["viz"]
            sel = state["selected"]
            dim = (sel is not None)

            # 1. 组件
            for comp in reversed(viz.get_component_list_sorted()):
                name = comp["name"]
                box = comp["info"]["box"]
                bx, by = min(box[0], box[2]), min(box[1], box[3])
                bw, bh = abs(box[2]-box[0]), abs(box[3]-box[1])
                
                fill_opacity = 0.05
                stroke = "blue"; sw = 2
                if dim: 
                    if sel["type"] == "component" and sel["name"] == name: stroke, sw, op = ("red", 4, 0)
                    else: stroke, op = ("rgba(0,0,255,0.3)", 0.02)
                else: op = fill_opacity
                
                svg_content += f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" fill="rgba(0,0,255,{op})" stroke="{stroke}" stroke-width="{sw}" />'
                if not dim or (sel["type"]=="component" and sel["name"]==name):
                    svg_content += f'<text x="{bx}" y="{by-5}" fill="{stroke}" font-size="16" font-weight="bold">{name}</text>'

            # 2. 连线
            for idx, conn in enumerate(viz.data["connections"]):
                center = viz.get_connection_centroid(idx)
                if not center: continue
                
                network_high = False
                if sel:
                    if sel["type"] == "conn_center" and sel["index"] == idx: network_high = True
                    elif sel["type"] == "component":
                        for node in conn["nodes"]:
                            if node["component"] == sel["name"]: network_high = True; break
                    elif sel["type"] == "port":
                         for node in conn["nodes"]:
                            if node["component"] == sel["comp"] and node["port"] == sel["port"]: network_high = True; break
                
                c_color = "red" if network_high else ("#00cc00" if not dim else "rgba(0,200,0,0.2)")
                svg_content += f'<circle cx="{center[0]}" cy="{center[1]}" r="{6 if network_high else 4}" fill="{c_color}" stroke="white" stroke-width="1" />'
                
                for node in conn["nodes"]:
                    p_coord = viz.get_port_coord(node["component"], node["port"])
                    if p_coord:
                        edge_high = False
                        if network_high: edge_high = True
                        elif sel and sel["type"] == "conn_edge" and sel["index"] == idx:
                            if sel["node"]["component"] == node["component"] and sel["node"]["port"] == node["port"]:
                                edge_high = True
                        
                        l_color = "red" if edge_high else ("#00cc00" if not dim else "rgba(0,200,0,0.2)")
                        l_width = 4 if edge_high else 2
                        
                        svg_content += f'<line x1="{p_coord[0]}" y1="{p_coord[1]}" x2="{center[0]}" y2="{center[1]}" stroke="{l_color}" stroke-width="{l_width}" />'

            # 3. 端口
            all_ports = []
            for pname, pinfo in viz.data["external_ports"].items(): 
                all_ports.append({"comp": "external", "name": pname, "coord": pinfo["coord"], "type": "ext"})
            for cname, cinfo in viz.data["components"].items():
                for p in cinfo["ports"]: 
                    all_ports.append({"comp": cname, "name": p["name"], "coord": p["coord"], "type": "int"})
            
            for p in all_ports:
                cx, cy = p["coord"]
                is_ext = (p["type"] == "ext")
                r = 10 if is_ext else 5
                p_high = False
                if sel and sel["type"] == "port" and sel["comp"] == p["comp"] and sel["port"] == p["name"]: p_high = True
                if state["connect_start"] and state["connect_start"]["comp"] == p["comp"] and state["connect_start"]["port"] == p["name"]: p_high = True
                
                fill = "yellow" if p_high else ("orange" if is_ext else "purple")
                stroke = "black" if p_high else "white"
                if dim and not p_high: fill = "#cccccc"
                
                svg_content += f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{2 if p_high else 1}" />'

        # 4. 临时框
        if state["temp_draw"]:
            s, c = state["temp_draw"]['start'], state["temp_draw"]['curr']
            x, y, w_box, h_box = min(s[0], c[0]), min(s[1], c[1]), abs(s[0]-c[0]), abs(s[1]-c[1])
            svg_content += f'<rect x="{x}" y="{y}" width="{w_box}" height="{h_box}" fill="none" stroke="red" stroke-width="3" stroke-dasharray="5,5" />'

        img_comp.content = f'<svg viewBox="0 0 {w} {h}">{svg_content}</svg>'

    # --- 弹窗逻辑 ---
    async def open_add_comp_dialog(box):
        save_history()
        with ui.dialog() as dialog, ui.card().classes('min-w-[300px]'):
            ui.label('新增组件').classes('text-lg font-bold')
            name_input = ui.input('名称').props('autofocus')
            type_input = ui.input('类型')
            with ui.row().classes('w-full justify-end'):
                ui.button('取消', on_click=dialog.close).props('flat')
                def on_confirm():
                    if not name_input.value: return
                    success, msg = state["viz"].add_component(name_input.value, type_input.value, box)
                    if success: dialog.close(); refresh_canvas()
                    else: ui.notify(msg, color='negative')
                ui.button('确定', on_click=on_confirm)
        dialog.open()

    async def open_add_port_dialog(comp_name, coord):
        save_history()
        with ui.dialog() as dialog, ui.card().classes('min-w-[300px]'):
            ui.label(f'新增端口 ({comp_name})').classes('text-lg font-bold')
            name_input = ui.input('名称').props('autofocus')
            type_input = ui.input('类型')
            with ui.row().classes('w-full justify-end'):
                ui.button('取消', on_click=dialog.close).props('flat')
                def on_confirm():
                    if not name_input.value: return
                    success, msg = state["viz"].add_port(comp_name, name_input.value, type_input.value, coord)
                    if success: dialog.close(); refresh_canvas()
                    else: ui.notify(msg, color='negative')
                ui.button('确定', on_click=on_confirm)
        dialog.open()

    # --- 鼠标事件处理 ---
    async def handle_mouse(e: events.MouseEventArguments):
        viz = state["viz"]
        mode = state["mode"]
        x, y = e.image_x, e.image_y

        if mode == 'ADD_COMP':
            if e.type == 'mousedown': state["temp_draw"] = {'start': (x, y), 'curr': (x, y)}
            elif e.type == 'mousemove' and state["temp_draw"]:
                state["temp_draw"]['curr'] = (x, y)
                refresh_canvas(draw_only_temp=True) 
            elif e.type == 'mouseup' and state["temp_draw"]:
                s, end = state["temp_draw"]['start'], (x, y)
                box = [min(s[0], end[0]), min(s[1], end[1]), max(s[0], end[0]), max(s[1], end[1])]
                state["temp_draw"] = None
                refresh_canvas()
                if abs(box[2]-box[0]) > 5: await open_add_comp_dialog(box)

        elif e.type == 'mousedown':
            hit = viz.hit_test(x, y)
            if mode == 'VIEW':
                state["selected"] = hit
                update_info_panel(hit)
                refresh_canvas()
            elif mode == 'ADD_PORT':
                comp_hit = viz.hit_test(x, y)
                target = comp_hit["name"] if (comp_hit and comp_hit["type"] == "component") else "external"
                await open_add_port_dialog(target, (x, y))
            elif mode == 'CONNECT':
                if not hit:
                    state["connect_start"] = None
                    refresh_canvas(); return
                if not state["connect_start"]:
                    if hit["type"] == "port":
                        state["connect_start"] = hit
                        ui.notify(f"起点: {hit['port']}")
                        refresh_canvas()
                else:
                    start = state["connect_start"]
                    save_history()
                    if hit["type"] == "port":
                        if start != hit:
                            viz.connect_nodes(start, hit)
                            ui.notify("连接成功"); state["connect_start"] = None; refresh_canvas()
                    elif hit["type"] in ["conn_center", "conn_edge"]:
                        viz.add_to_connection(hit["index"], start)
                        ui.notify("已合并"); state["connect_start"] = None; refresh_canvas()

    def save_to_gradio():
        SESSIONS[session_id]["result"] = state["viz"].export_json()
        SESSIONS[session_id]["done"] = True
        ui.notify("保存成功！数据已传回 Gradio。", type='positive')
        # 弹窗提示关闭
        with ui.dialog() as d, ui.card():
            ui.label("标注完成").classes("text-xl font-bold text-green-600")
            ui.label("您可以关闭此页面了。")
            ui.button("关闭", on_click=lambda: ui.run_javascript("window.close()"))
        d.open()

    # ==========================================
    # 4. 页面布局
    # ==========================================
    
    ui.add_head_html('''<style>body { margin: 0; padding: 0; overflow: hidden; background-color: #e5e7eb; }</style>''')
    
    with ui.header().classes('bg-slate-800 items-center h-14 shadow-lg'):
        ui.icon('settings_input_component', color='white', size='md').classes('ml-2')
        ui.label('Circuit Annotator').classes('text-white text-lg font-bold ml-2')
        ui.space()
        state["ui"]["undo_btn"] = ui.button('撤销', icon='undo', on_click=undo).props('flat color=white')
        state["ui"]["undo_btn"].disable()
        ui.button('保存并返回', on_click=save_to_gradio, icon='save').props('unelevated color=green-600')

    with ui.row().classes('w-full h-[calc(100vh-3.5rem)] no-wrap gap-0'):
        # 左侧边栏
        with ui.column().classes('w-72 h-full bg-white border-r p-4 gap-4 shrink-0 z-10'):
            with ui.card().classes('w-full p-2 bg-slate-50 gap-2'):
                ui.label('模式').classes('font-bold text-xs text-slate-500 mb-1')
                btns = state["ui"]["mode_btns"]
                btns['VIEW'] = ui.button('查看/编辑', icon='edit', on_click=lambda: set_mode('VIEW')).classes('w-full')
                btns['ADD_COMP'] = ui.button('新增组件', icon='crop_free', on_click=lambda: set_mode('ADD_COMP')).classes('w-full')
                btns['ADD_PORT'] = ui.button('新增端口', icon='radio_button_checked', on_click=lambda: set_mode('ADD_PORT')).classes('w-full')
                btns['CONNECT'] = ui.button('连线', icon='hub', on_click=lambda: set_mode('CONNECT')).classes('w-full')
                set_mode('VIEW')
            state["ui"]["status"] = ui.label('').classes('text-xs text-gray-500 w-full text-center bg-gray-100 rounded p-1')
            ui.separator()
            with ui.column().classes('w-full border rounded p-3 bg-white flex-grow') as info_col:
                state["ui"]["info_panel"] = info_col

        # 右侧画布区
        with ui.column().classes('flex-grow h-full bg-gray-500 relative overflow-auto items-start justify-start'):
            # 画布 (修正: img_src 直接作为第一个参数)
            img = ui.interactive_image(
                img_src, 
                events=['mousedown', 'mouseup', 'mousemove'], 
                on_mouse=handle_mouse, 
                cross=True
            ).style('width: 100%; height: auto; transform-origin: top left;')
            state["ui"]["img"] = img

            # 缩放控件 (之前缺少的代码)
            with ui.column().classes('fixed bottom-4 right-4 gap-2 z-50'):
                ui.button(icon='add', on_click=zoom_in).props('round dense color=white text-color=black shadow')
                ui.button(icon='restart_alt', on_click=zoom_reset).props('round dense color=white text-color=black shadow')
                ui.button(icon='remove', on_click=zoom_out).props('round dense color=white text-color=black shadow')

            # 原图悬浮窗 (修正: 直接传参)
            with ui.card().classes('fixed top-16 right-4 z-50 w-80 bg-white p-2 shadow-xl border border-gray-300 opacity-90 hover:opacity-100 transition-opacity'):
                ui.label('原图参照').classes('text-xs font-bold text-gray-500 mb-1')
                ui.image(img_src).classes('w-full rounded')

    # 初始刷新
    ui.timer(0.1, refresh_canvas, once=True)
    ui.keyboard(on_key=lambda e: undo() if (e.modifiers.ctrl and e.key=='z') else (delete_selection() if e.key=='Delete' else None))

ui.run(port=8060, title="NiceGUI Annotation Server", storage_secret="secret")