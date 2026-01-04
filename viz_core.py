import json
import math
import copy

class SystemBlockViz:
    def __init__(self, json_data):
        self.data = json_data if isinstance(json_data, dict) else json.loads(json_data)
        self.ensure_structure()

    def clone_data(self):
        return copy.deepcopy(self.data)

    def restore_data(self, old_data):
        self.data = old_data

    def ensure_structure(self):
        if "components" not in self.data: self.data["components"] = {}
        if "external_ports" not in self.data: self.data["external_ports"] = {}
        if "connections" not in self.data: self.data["connections"] = []

    # --- 辅助计算 ---
    def get_component_list_sorted(self):
        comps = []
        for name, info in self.data["components"].items():
            box = info["box"]
            area = abs((box[2] - box[0]) * (box[3] - box[1]))
            comps.append({"name": name, "info": info, "area": area})
        return sorted(comps, key=lambda x: x["area"])

    def get_connection_centroid(self, conn_idx):
        conn = self.data["connections"][conn_idx]
        if not conn["nodes"]: return None
        sum_x, sum_y, count = 0, 0, 0
        for node in conn["nodes"]:
            coord = self.get_port_coord(node["component"], node["port"])
            if coord:
                sum_x += coord[0]; sum_y += coord[1]; count += 1
        if count == 0: return None
        return [sum_x / count, sum_y / count]

    def get_port_coord(self, comp_name, port_name):
        if comp_name == "external":
            if port_name in self.data["external_ports"]:
                return self.data["external_ports"][port_name]["coord"]
        else:
            if comp_name in self.data["components"]:
                for p in self.data["components"][comp_name]["ports"]:
                    if p["name"] == port_name: return p["coord"]
        return None

    def _dist(self, x1, y1, x2, y2):
        return math.sqrt((x1-x2)**2 + (y1-y2)**2)

    def _dist_point_to_segment(self, px, py, x1, y1, x2, y2):
        l2 = (x1-x2)**2 + (y1-y2)**2
        if l2 == 0: return self._dist(px, py, x1, y1)
        t = ((px-x1)*(x2-x1) + (py-y1)*(y2-y1)) / l2
        t = max(0, min(1, t))
        proj_x = x1 + t * (x2-x1)
        proj_y = y1 + t * (y2-y1)
        return self._dist(px, py, proj_x, proj_y)

    # --- 命中检测 (调整了阈值，让外部端口更容易被点中) ---
    def hit_test(self, x, y):
        # 1. 连接中心点
        for idx, conn in enumerate(self.data["connections"]):
            center = self.get_connection_centroid(idx)
            if center and self._dist(x, y, center[0], center[1]) < 8:
                return {"type": "conn_center", "index": idx}
        
        # 2. 端口 (优先级调高，阈值调大到 10px)
        for name, info in self.data["external_ports"].items():
            if self._dist(x, y, info["coord"][0], info["coord"][1]) < 10: 
                return {"type": "port", "comp": "external", "port": name}
        
        for comp_name, comp_info in self.data["components"].items():
            for p in comp_info["ports"]:
                if self._dist(x, y, p["coord"][0], p["coord"][1]) < 8:
                     return {"type": "port", "comp": comp_name, "port": p["name"]}

        # 3. 连线分支
        for idx, conn in enumerate(self.data["connections"]):
            center = self.get_connection_centroid(idx)
            if not center: continue
            for node in conn["nodes"]:
                p_coord = self.get_port_coord(node["component"], node["port"])
                if p_coord:
                    if self._dist_point_to_segment(x, y, p_coord[0], p_coord[1], center[0], center[1]) < 5:
                        return {"type": "conn_edge", "index": idx, "node": node}
        
        # 4. 组件
        sorted_comps = self.get_component_list_sorted()
        for item in sorted_comps:
            box = item["info"]["box"]
            bx1, by1, bx2, by2 = min(box[0], box[2]), min(box[1], box[3]), max(box[0], box[2]), max(box[1], box[3])
            if bx1 <= x <= bx2 and by1 <= y <= by2:
                return {"type": "component", "name": item["name"]}
        return None

    # --- CRUD (保持不变) ---
    def add_component(self, name, c_type, box):
        if name in self.data["components"] or name in self.data["external_ports"]: return False, "名字已存在"
        self.data["components"][name] = {
            "type": c_type,
            "box": [min(box[0], box[2]), min(box[1], box[3]), max(box[0], box[2]), max(box[1], box[3])],
            "ports": []
        }
        return True, ""
    
    def rename_component(self, old_name, new_name):
        if old_name == new_name: return True, ""
        if new_name in self.data["components"] or new_name in self.data["external_ports"]: return False, "新名字已存在"
        comp_data = self.data["components"].pop(old_name)
        self.data["components"][new_name] = comp_data
        for conn in self.data["connections"]:
            for node in conn["nodes"]:
                if node["component"] == old_name: node["component"] = new_name
        return True, ""

    def update_component_type(self, name, new_type):
        if name in self.data["components"]:
            self.data["components"][name]["type"] = new_type

    def delete_component(self, name):
        if name in self.data["components"]:
            del self.data["components"][name]
            self._cleanup_connections(name, None)

    def add_port(self, comp_name, port_name, port_type, coord):
        if comp_name == "external":
            if port_name in self.data["external_ports"]: return False, "重名"
            self.data["external_ports"][port_name] = {"type": port_type, "coord": [int(coord[0]), int(coord[1])]}
        else:
            ports = self.data["components"][comp_name]["ports"]
            for p in ports:
                if p["name"] == port_name: return False, "重名"
            ports.append({"name": port_name, "coord": [int(coord[0]), int(coord[1])]})
        return True, ""
    
    def rename_port(self, comp_name, old_port_name, new_port_name):
        if old_port_name == new_port_name: return True, ""
        if comp_name == "external":
            if new_port_name in self.data["external_ports"]: return False, "重名"
            self.data["external_ports"][new_port_name] = self.data["external_ports"].pop(old_port_name)
        else:
            comp = self.data["components"][comp_name]
            for p in comp["ports"]:
                if p["name"] == new_port_name: return False, "重名"
            for p in comp["ports"]:
                if p["name"] == old_port_name:
                    p["name"] = new_port_name; break
        for conn in self.data["connections"]:
            for node in conn["nodes"]:
                if node["component"] == comp_name and node["port"] == old_port_name:
                    node["port"] = new_port_name
        return True, ""

    def delete_port(self, comp_name, port_name):
        if comp_name == "external":
            if port_name in self.data["external_ports"]:
                del self.data["external_ports"][port_name]
                self._cleanup_connections("external", port_name)
        else:
            comp = self.data["components"].get(comp_name)
            if comp:
                comp["ports"] = [p for p in comp["ports"] if p["name"] != port_name]
                self._cleanup_connections(comp_name, port_name)

    def connect_nodes(self, node_a, node_b):
        idx_a = self._find_conn_index(node_a)
        idx_b = self._find_conn_index(node_b)
        target_a = {"component": node_a['comp'], "port": node_a['port']}
        target_b = {"component": node_b['comp'], "port": node_b['port']}
        if idx_a is not None and idx_b is not None:
            if idx_a == idx_b: return
            self.data["connections"][idx_a]["nodes"].extend(self.data["connections"][idx_b]["nodes"])
            del self.data["connections"][idx_b]
        elif idx_a is not None: self.data["connections"][idx_a]["nodes"].append(target_b)
        elif idx_b is not None: self.data["connections"][idx_b]["nodes"].append(target_a)
        else: self.data["connections"].append({"nodes": [target_a, target_b], "points": []})

    def add_to_connection(self, conn_idx, node_struct):
        target = {"component": node_struct['comp'], "port": node_struct['port']}
        for n in self.data["connections"][conn_idx]["nodes"]:
            if n["component"] == target["component"] and n["port"] == target["port"]: return
        self.data["connections"][conn_idx]["nodes"].append(target)

    def delete_connection_node(self, conn_idx, node_struct=None):
        if node_struct is None:
            del self.data["connections"][conn_idx]
            return
        conn = self.data["connections"][conn_idx]
        conn["nodes"] = [n for n in conn["nodes"] if not (n["component"] == node_struct['component'] and n["port"] == node_struct['port'])]
        if len(conn["nodes"]) < 2: del self.data["connections"][conn_idx]

    def _find_conn_index(self, node_struct):
        for i, conn in enumerate(self.data["connections"]):
            for n in conn["nodes"]:
                if n["component"] == node_struct['comp'] and n["port"] == node_struct['port']: return i
        return None

    def _cleanup_connections(self, comp_name, port_name=None):
        to_remove = []
        for i, conn in enumerate(self.data["connections"]):
            new_nodes = []
            for n in conn["nodes"]:
                hit_comp = (n["component"] == comp_name)
                hit_port = (n["port"] == port_name) if port_name else True
                if not (hit_comp and hit_port): new_nodes.append(n)
            conn["nodes"] = new_nodes
            if len(conn["nodes"]) < 2: to_remove.append(i)
        for i in sorted(to_remove, reverse=True): del self.data["connections"][i]

    def export_json(self):
        return json.dumps(self.data, indent=2, ensure_ascii=False)