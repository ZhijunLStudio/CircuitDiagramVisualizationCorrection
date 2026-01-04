from nicegui import ui, events
import json
import base64
import io
from PIL import Image
from viz_core import SystemBlockViz

app_state = {
    "viz": None,
    "mode": "VIEW",       
    "img_src": None,      
    "img_size": (1000, 1000), 
    "selected": None,     
    "temp_draw": None,    
    "connect_start": None,
    "ui": {
        "img": None,      
        "status": None,   
        "info_panel": None, 
        "mode_btns": {},  
        "ref_img": None,  
    }
}

def set_mode(mode):
    app_state["mode"] = mode
    app_state["selected"] = None
    app_state["connect_start"] = None
    app_state["temp_draw"] = None
    btns = app_state["ui"]["mode_btns"]
    for k, btn in btns.items():
        if k == mode: btn.props('color=primary')
        else: btn.props('color=white text-color=black') 
    tips = {
        'VIEW': '【查看/编辑】点击连线分支可删除单根线，点击中心点删除整个网络。',
        'ADD_COMP': '【画框模式】拖拽画框，创建新组件。',
        'ADD_PORT': '【端口模式】点击添加端口 (框内自动归属)。',
        'CONNECT': '【连线模式】点击端口A -> 端口B (或点击连接线)。'
    }
    if app_state["ui"]["status"]: app_state["ui"]["status"].set_text(tips.get(mode, ''))
    update_info_panel(None)
    refresh_canvas()

def handle_image_upload(e: events.UploadEventArguments):
    data = e.content.read()
    try:
        img_obj = Image.open(io.BytesIO(data))
        app_state["img_size"] = img_obj.size
    except:
        ui.notify("图片无法解析", color='negative'); return
    b64 = base64.b64encode(data).decode('utf-8')
    src = f'data:image/png;base64,{b64}'
    app_state["img_src"] = src
    if app_state["ui"]["img"]: app_state["ui"]["img"].set_source(src)
    if app_state["ui"]["ref_img"]:
        app_state["ui"]["ref_img"].set_source(src)
        app_state["ui"]["ref_img"].classes(remove='hidden')
    refresh_canvas()
    ui.notify(f"图片加载成功: {app_state['img_size']}")

def handle_json_upload(e: events.UploadEventArguments):
    try:
        content = e.content.read().decode('utf-8')
        app_state["viz"] = SystemBlockViz(content)
        refresh_canvas()
        ui.notify("JSON 数据已加载")
        set_mode('VIEW')
    except Exception as ex:
        ui.notify(f"JSON 错误: {ex}", color='negative')

def delete_selection():
    sel = app_state["selected"]
    viz = app_state["viz"]
    if not sel or not viz: return

    if sel["type"] == "component":
        viz.delete_component(sel["name"])
    elif sel["type"] == "port":
        viz.delete_port(sel["comp"], sel["port"])
    elif sel["type"] == "conn_center":
        # 删除整个网络
        viz.delete_connection_node(sel["index"], None)
    elif sel["type"] == "conn_edge":
        # 关键：只删除这一根线（这一个节点）
        viz.delete_connection_node(sel["index"], sel["node"])
    
    ui.notify("已删除")
    app_state["selected"] = None
    update_info_panel(None)
    refresh_canvas()

def download_json():
    if not app_state["viz"]: return
    ui.download(app_state["viz"].export_json().encode('utf-8'), 'circuit_annotation.json')

# --- 属性修改回调 ---
def on_component_rename(new_val):
    sel = app_state["selected"]
    viz = app_state["viz"]
    if not sel or not viz or sel["type"] != "component": return
    if new_val == sel["name"]: return
    success, msg = viz.rename_component(sel["name"], new_val)
    if success:
        sel["name"] = new_val
        ui.notify(f"重命名为: {new_val}")
        refresh_canvas()
    else:
        ui.notify(f"失败: {msg}", color='negative')
        update_info_panel(sel)

def on_component_type_change(new_val):
    sel = app_state["selected"]
    viz = app_state["viz"]
    if not sel or not viz or sel["type"] != "component": return
    viz.update_component_type(sel["name"], new_val)

def on_port_rename(new_val):
    sel = app_state["selected"]
    viz = app_state["viz"]
    if not sel or not viz or sel["type"] != "port": return
    if new_val == sel["port"]: return
    success, msg = viz.rename_port(sel["comp"], sel["port"], new_val)
    if success:
        sel["port"] = new_val
        ui.notify(f"重命名为: {new_val}")
        refresh_canvas()
    else:
        ui.notify(f"失败: {msg}", color='negative')
        update_info_panel(sel)

# --- 界面组件更新 ---
def update_info_panel(hit):
    panel = app_state["ui"]["info_panel"]
    if not panel: return
    panel.clear()
    if not hit:
        with panel: ui.label("未选中对象").classes('text-gray-400 italic')
        return

    viz = app_state["viz"]
    with panel:
        ui.label('属性编辑').classes('font-bold text-gray-700 mb-2')
        
        if hit["type"] == "component":
            ui.input('组件名称', value=hit["name"], on_change=lambda e: on_component_rename(e.value)).classes('w-full')
            curr_type = viz.data["components"][hit["name"]].get("type", "")
            ui.input('组件类型', value=curr_type, on_change=lambda e: on_component_type_change(e.value)).classes('w-full')
        
        elif hit["type"] == "port":
            ui.input('端口名称', value=hit["port"], on_change=lambda e: on_port_rename(e.value)).classes('w-full')
            ui.label(f"所属: {hit['comp']}").classes('text-sm text-gray-600 mt-2')

        elif hit["type"] == "conn_center":
            ui.label("连接网络 (中心)").classes('text-lg text-green-700 font-bold')
            ui.label("点击此中心可删除整个网络。").classes('text-xs text-gray-500')
            ui.separator().classes('my-4')
            ui.button('删除 整个网络', on_click=delete_selection, color='red').classes('w-full')
            return # 单独处理按钮

        elif hit["type"] == "conn_edge":
            ui.label("连线分支 (Edge)").classes('text-lg text-green-600 font-bold')
            node = hit["node"]
            ui.label(f"连接端点: {node['component']} -> {node['port']}").classes('text-sm text-gray-700 my-2')
            ui.separator().classes('my-4')
            ui.button('断开 此连线', on_click=delete_selection, color='orange').classes('w-full')
            return

        ui.separator().classes('my-4')
        ui.button('删除此对象', on_click=delete_selection, color='red', icon='delete').classes('w-full')

# --- 绘图核心 ---
def refresh_canvas(draw_only_temp=False):
    img_comp = app_state["ui"]["img"]
    w, h = app_state["img_size"]
    if not img_comp: return
    if not app_state["viz"] and not app_state["temp_draw"]:
        img_comp.content = f'<svg viewBox="0 0 {w} {h}"></svg>'
        return

    svg_content = ""
    if not draw_only_temp and app_state["viz"]:
        viz = app_state["viz"]
        sel = app_state["selected"]
        conn_start = app_state["connect_start"]
        dim_mode = (sel is not None)

        # 1. 组件
        sorted_comps = viz.get_component_list_sorted()
        for comp in reversed(sorted_comps):
            name = comp["name"]
            box = comp["info"]["box"]
            bx, by = min(box[0], box[2]), min(box[1], box[3])
            bw, bh = abs(box[2]-box[0]), abs(box[3]-box[1])
            fill_opacity = 0.05
            stroke = "blue"; sw = 2
            
            if dim_mode:
                is_target = (sel["type"] == "component" and sel["name"] == name)
                if is_target: stroke = "red"; sw = 4; fill_opacity = 0
                else: stroke = "rgba(0,0,255,0.3)"; fill_opacity = 0.02
            
            svg_content += f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" fill="rgba(0,0,255,{fill_opacity})" stroke="{stroke}" stroke-width="{sw}" />'
            if not dim_mode or (sel["type"] == "component" and sel["name"] == name):
                svg_content += f'<text x="{bx}" y="{by-5}" fill="{stroke}" font-size="16" font-weight="bold">{name}</text>'

        # 2. 连线 (区分 中心 和 分支)
        for idx, conn in enumerate(viz.data["connections"]):
            center = viz.get_connection_centroid(idx)
            if not center: continue
            
            # 判断整个网络是否高亮 (中心点选中)
            center_high = (sel and sel["type"] == "conn_center" and sel["index"] == idx)
            
            # 绘制中心点
            c_color = "red" if center_high else ("#00cc00" if not dim_mode else "rgba(0,200,0,0.2)")
            svg_content += f'<circle cx="{center[0]}" cy="{center[1]}" r="{6 if center_high else 4}" fill="{c_color}" stroke="white" stroke-width="1" />'

            # 绘制分支线
            for node in conn["nodes"]:
                p_coord = viz.get_port_coord(node["component"], node["port"])
                if p_coord:
                    # 判断这根线是否高亮
                    edge_high = False
                    if center_high: edge_high = True # 选中中心，全亮
                    elif sel and sel["type"] == "conn_edge" and sel["index"] == idx:
                        # 选中某根线，判断是不是这根
                        if sel["node"]["component"] == node["component"] and sel["node"]["port"] == node["port"]:
                            edge_high = True
                    
                    # 端口/组件反向高亮
                    if sel and sel["type"] == "port" and sel["comp"] == node["component"] and sel["port"] == node["port"]: edge_high = True
                    if sel and sel["type"] == "component" and sel["name"] == node["component"]: edge_high = True

                    l_color = "red" if edge_high else ("#00cc00" if not dim_mode else "rgba(0,200,0,0.2)")
                    l_width = 4 if edge_high else 3

                    svg_content += f'<line x1="{p_coord[0]}" y1="{p_coord[1]}" x2="{center[0]}" y2="{center[1]}" stroke="{l_color}" stroke-width="{l_width}" />'

        # 3. 端口
        all_ports = []
        for pname, pinfo in viz.data["external_ports"].items(): all_ports.append({"comp": "external", "name": pname, "coord": pinfo["coord"], "type": "ext"})
        for cname, cinfo in viz.data["components"].items():
            for p in cinfo["ports"]: all_ports.append({"comp": cname, "name": p["name"], "coord": p["coord"], "type": "int"})
        for p in all_ports:
            cx, cy = p["coord"]
            is_ext = (p["type"] == "ext")
            r = 8 if is_ext else 5
            p_high = False
            if sel and sel["type"] == "port" and sel["comp"] == p["comp"] and sel["port"] == p["name"]: p_high = True
            if conn_start and conn_start["comp"] == p["comp"] and conn_start["port"] == p["name"]: p_high = True
            fill = "yellow" if p_high else ("orange" if is_ext else "purple")
            stroke = "black" if p_high else "white"
            if dim_mode and not p_high: fill = "#cccccc"
            svg_content += f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{2 if p_high else 1}" />'

    if app_state["temp_draw"]:
        s, c = app_state["temp_draw"]['start'], app_state["temp_draw"]['curr']
        x, y = min(s[0], c[0]), min(s[1], c[1])
        w, h = abs(s[0]-c[0]), abs(s[1]-c[1])
        svg_content += f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="red" stroke-width="3" stroke-dasharray="5,5" />'

    img_comp.content = f'<svg viewBox="0 0 {w} {h}">{svg_content}</svg>'

# --- 交互 ---
async def open_add_comp_dialog(box):
    with ui.dialog() as dialog, ui.card().classes('min-w-[300px]'):
        ui.label('新增组件').classes('text-lg font-bold')
        name_input = ui.input('名称').props('autofocus')
        type_input = ui.input('类型')
        with ui.row().classes('w-full justify-end'):
            ui.button('取消', on_click=dialog.close).props('flat')
            def on_confirm():
                if not name_input.value: return
                success, msg = app_state["viz"].add_component(name_input.value, type_input.value, box)
                if success: dialog.close(); refresh_canvas()
                else: ui.notify(msg, color='negative')
            ui.button('确定', on_click=on_confirm)
    dialog.open()

async def open_add_port_dialog(comp_name, coord):
    with ui.dialog() as dialog, ui.card().classes('min-w-[300px]'):
        ui.label(f'新增端口 ({comp_name})').classes('text-lg font-bold')
        name_input = ui.input('名称').props('autofocus')
        type_input = ui.input('类型')
        with ui.row().classes('w-full justify-end'):
            ui.button('取消', on_click=dialog.close).props('flat')
            def on_confirm():
                if not name_input.value: return
                success, msg = app_state["viz"].add_port(comp_name, name_input.value, type_input.value, coord)
                if success: dialog.close(); refresh_canvas()
                else: ui.notify(msg, color='negative')
            ui.button('确定', on_click=on_confirm)
    dialog.open()

async def handle_mouse(e: events.MouseEventArguments):
    if not app_state["viz"]: return
    viz = app_state["viz"]
    mode = app_state["mode"]
    x, y = e.image_x, e.image_y

    if mode == 'ADD_COMP':
        if e.type == 'mousedown': app_state["temp_draw"] = {'start': (x, y), 'curr': (x, y)}
        elif e.type == 'mousemove' and app_state["temp_draw"]:
            app_state["temp_draw"]['curr'] = (x, y)
            refresh_canvas(draw_only_temp=True) 
        elif e.type == 'mouseup' and app_state["temp_draw"]:
            s, end = app_state["temp_draw"]['start'], (x, y)
            box = [min(s[0], end[0]), min(s[1], end[1]), max(s[0], end[0]), max(s[1], end[1])]
            app_state["temp_draw"] = None
            refresh_canvas()
            if abs(box[2]-box[0]) > 5: await open_add_comp_dialog(box)

    elif e.type == 'mousedown':
        hit = viz.hit_test(x, y)
        if mode == 'VIEW':
            app_state["selected"] = hit
            update_info_panel(hit)
            refresh_canvas()
        elif mode == 'ADD_PORT':
            comp_hit = viz.hit_test(x, y)
            target = comp_hit["name"] if (comp_hit and comp_hit["type"] == "component") else "external"
            await open_add_port_dialog(target, (x, y))
        elif mode == 'CONNECT':
            if not hit:
                app_state["connect_start"] = None
                refresh_canvas(); return
            if not app_state["connect_start"]:
                if hit["type"] == "port":
                    app_state["connect_start"] = hit
                    ui.notify(f"起点: {hit['port']}")
                    refresh_canvas()
            else:
                start = app_state["connect_start"]
                if hit["type"] == "port":
                    if start != hit:
                        viz.connect_nodes(start, hit)
                        ui.notify("连接成功")
                        app_state["connect_start"] = None
                        refresh_canvas()
                elif hit["type"] in ["conn_center", "conn_edge"]:
                    # 点击任何连接部分都算合并网络
                    viz.add_to_connection(hit["index"], start)
                    ui.notify("已合并")
                    app_state["connect_start"] = None
                    refresh_canvas()

def main():
    ui.add_head_html('''<style>body { margin: 0; padding: 0; overflow: hidden; background-color: #e5e7eb; }</style>''')
    with ui.header().classes('bg-slate-800 items-center h-14 shadow-lg'):
        ui.icon('settings_input_component', color='white', size='md').classes('ml-2')
        ui.label('Circuit Labeler Pro').classes('text-white text-lg font-bold ml-2')
        ui.space()
        ui.keyboard(on_key=lambda e: delete_selection() if e.key == 'Delete' else None)
        ui.button('保存 JSON', on_click=download_json, icon='save').props('unelevated color=green-600')

    with ui.row().classes('w-full h-[calc(100vh-3.5rem)] no-wrap gap-0'):
        with ui.column().classes('w-72 h-full bg-white border-r border-gray-300 p-4 gap-4 shadow-md shrink-0 z-20'):
            with ui.card().classes('w-full p-2 bg-slate-50'):
                ui.label('1. 文件加载').classes('font-bold text-xs text-slate-500 mb-1')
                ui.upload(label='图片', on_upload=handle_image_upload, auto_upload=True).props('flat dense bordered color=primary').classes('w-full mb-1')
                ui.upload(label='JSON', on_upload=handle_json_upload, auto_upload=True).props('flat dense bordered color=secondary').classes('w-full')
            with ui.card().classes('w-full p-2 bg-slate-50 gap-2'):
                ui.label('2. 模式').classes('font-bold text-xs text-slate-500 mb-1')
                btns = app_state["ui"]["mode_btns"]
                btns['VIEW'] = ui.button('查看/编辑', icon='edit', on_click=lambda: set_mode('VIEW')).classes('w-full')
                btns['ADD_COMP'] = ui.button('新增组件', icon='crop_free', on_click=lambda: set_mode('ADD_COMP')).classes('w-full')
                btns['ADD_PORT'] = ui.button('新增端口', icon='radio_button_checked', on_click=lambda: set_mode('ADD_PORT')).classes('w-full')
                btns['CONNECT'] = ui.button('连线', icon='hub', on_click=lambda: set_mode('CONNECT')).classes('w-full')
                set_mode('VIEW')
            app_state["ui"]["status"] = ui.label('准备就绪').classes('text-xs text-gray-500 w-full text-center bg-gray-100 rounded p-1')
            ui.separator()
            with ui.column().classes('w-full border border-gray-200 rounded p-3 bg-white flex-grow') as info_col:
                app_state["ui"]["info_panel"] = info_col
                ui.label('未选中对象').classes('text-gray-400 italic')

        with ui.column().classes('flex-grow h-full bg-gray-200 relative overflow-auto items-start justify-start p-4'):
            img = ui.interactive_image(events=['mousedown', 'mouseup', 'mousemove'], on_mouse=handle_mouse, cross=True).classes('shadow-2xl bg-white').style('width: 100%; height: auto;')
            app_state["ui"]["img"] = img
            with ui.card().classes('absolute top-4 right-4 z-10 w-96 bg-white p-2 shadow-xl border border-gray-300 opacity-90 hover:opacity-100 transition-opacity'):
                ui.label('原图参照').classes('text-xs font-bold text-gray-500 mb-1')
                ref_img = ui.image().classes('w-full rounded hidden')
                app_state["ui"]["ref_img"] = ref_img

    ui.run(title='Circuit Labeler Pro', port=8080)

if __name__ in {"__main__", "__mp_main__"}:
    main()