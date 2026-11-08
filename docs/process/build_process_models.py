#!/usr/bin/env python3
"""Build the OAEF V5 process models from one readable definition (no dependency, deterministic).

  python3 docs/process/build_process_models.py   -> oaef-v5-campaign.bpmn, oaef-v5-archimate.xml

- oaef-v5-campaign.bpmn: BPMN 2.0 collaboration with two pools (test engineer, CI scripts), with
  diagram interchange (DI) so bpmn.io, Camunda Modeler, Signavio or Bizagi render it as laid out here.
- oaef-v5-archimate.xml: ArchiMate 3.1 Open Exchange Format (imports into Archi: File > Import >
  Open Exchange XML), business / application / technology elements, relationships and one view.
These are documentation of the process the scripts implement; no script reads them.
"""
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------- BPMN
# (id, type, name, x, y) — task 100x80, event 36x36, gateway 50x50
ENGINEER = [
    ('E_start', 'startEvent', 'Campaign needed', 80, 102),
    ('E_spec', 'task', 'Write / review specification (models, oracle YAML)', 160, 80),
    ('E_trigger', 'task', 'Trigger campaign (gh workflow run)', 310, 80),
    ('E_investigate', 'task', 'Investigate report, Grafana, screenshots', 1210, 80),
    ('E_gw', 'exclusiveGateway', 'Defect?', 1365, 95),
    ('E_raise', 'task', 'Raise defect with run id and evidence zip', 1460, 80),
    ('E_end', 'endEvent', 'Campaign closed', 1620, 102),
]
CI = [
    ('C_start', 'startEvent', 'workflow_dispatch', 340, 312),
    ('C_compile', 'scriptTask', 'Compile specification, drift check', 420, 290),
    ('C_stack', 'scriptTask', 'Start Grafana LGTM (pinned)', 560, 290),
    ('C_case', 'scriptTask', 'Simulate journey, inject fault (S1)', 700, 290),
    ('C_collect', 'scriptTask', 'Collect from Tempo, Loki, Prometheus', 840, 290),
    ('C_verdict', 'scriptTask', 'Oracle verdict, classify, seal (SHA-256)', 980, 290),
    ('C_gw', 'exclusiveGateway', 'More cases?', 1115, 305),
    ('C_export', 'scriptTask', 'Allure, Playwright screenshots, zip, Xray JSON', 1210, 290),
    ('C_end', 'endEvent', 'Artifacts uploaded', 1360, 312),
]
FLOWS = [  # (id, source, target, name)
    ('F1', 'E_start', 'E_spec', ''), ('F2', 'E_spec', 'E_trigger', ''),
    ('F3', 'E_investigate', 'E_gw', ''), ('F4', 'E_gw', 'E_raise', 'yes'), ('F5', 'E_gw', 'E_end', 'no'),
    ('F6', 'E_raise', 'E_end', ''),
    ('F7', 'C_start', 'C_compile', ''), ('F8', 'C_compile', 'C_stack', ''), ('F9', 'C_stack', 'C_case', ''),
    ('F10', 'C_case', 'C_collect', ''), ('F11', 'C_collect', 'C_verdict', ''), ('F12', 'C_verdict', 'C_gw', ''),
    ('F13', 'C_gw', 'C_case', 'yes'), ('F14', 'C_gw', 'C_export', 'no'), ('F15', 'C_export', 'C_end', ''),
]
MESSAGES = [('M1', 'E_trigger', 'C_start', 'run request'), ('M2', 'C_export', 'E_investigate', 'reports, evidence, zip')]
SIZE = {'task': (100, 80), 'scriptTask': (100, 80), 'startEvent': (36, 36), 'endEvent': (36, 36), 'exclusiveGateway': (50, 50)}


def center(node):
    _, kind, _, x, y = node
    w, h = SIZE[kind]
    return x + w / 2, y + h / 2


def bpmn():
    nodes = {n[0]: n for n in ENGINEER + CI}
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" '
           'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" '
           'xmlns:di="http://www.omg.org/spec/DD/20100524/DI" id="oaef-v5" targetNamespace="https://github.com/gharbonnier78/mosip-observability-oracles">',
           '  <collaboration id="Collab">',
           '    <participant id="P_engineer" name="Test engineer (person)" processRef="Proc_engineer"/>',
           '    <participant id="P_ci" name="GitHub Actions: OAEF scripts (no AI at run time)" processRef="Proc_ci"/>']
    for mid, s, t, name in MESSAGES:
        out.append(f'    <messageFlow id="{mid}" name="{escape(name)}" sourceRef="{s}" targetRef="{t}"/>')
    out.append('  </collaboration>')
    for pid, items in (('Proc_engineer', ENGINEER), ('Proc_ci', CI)):
        ids = {n[0] for n in items}
        out.append(f'  <process id="{pid}" isExecutable="false">')
        for nid, kind, name, _, _ in items:
            ins = [f for f in FLOWS if f[2] == nid]
            outs = [f for f in FLOWS if f[1] == nid]
            body = ''.join(f'<incoming>{f[0]}</incoming>' for f in ins) + ''.join(f'<outgoing>{f[0]}</outgoing>' for f in outs)
            out.append(f'    <{kind} id="{nid}" name="{escape(name)}">{body}</{kind}>')
        for fid, s, t, name in FLOWS:
            if s in ids:
                out.append(f'    <sequenceFlow id="{fid}" name="{escape(name)}" sourceRef="{s}" targetRef="{t}"/>')
        out.append('  </process>')
    out.append('  <bpmndi:BPMNDiagram id="Diagram"><bpmndi:BPMNPlane id="Plane" bpmnElement="Collab">')
    for pid, y, h in (('P_engineer', 40, 160), ('P_ci', 240, 180)):
        out.append(f'    <bpmndi:BPMNShape id="{pid}_di" bpmnElement="{pid}" isHorizontal="true">'
                   f'<dc:Bounds x="20" y="{y}" width="1680" height="{h}"/></bpmndi:BPMNShape>')
    for nid, n in nodes.items():
        w, h = SIZE[n[1]]
        marker = ' isMarkerVisible="true"' if n[1] == 'exclusiveGateway' else ''
        out.append(f'    <bpmndi:BPMNShape id="{nid}_di" bpmnElement="{nid}"{marker}>'
                   f'<dc:Bounds x="{n[3]}" y="{n[4]}" width="{w}" height="{h}"/></bpmndi:BPMNShape>')
    for fid, s, t, _ in FLOWS + MESSAGES:
        (x1, y1), (x2, y2) = center(nodes[s]), center(nodes[t])
        if fid == 'F13':   # loop back under the tasks
            pts = [(x1, y1 + 25), (x1, 400), (x2, 400), (x2, y2 + 40)]
        elif fid == 'F5':   # around the raise task
            pts = [(x1, y1 - 25), (x1, 60), (x2, 60), (x2, y2 - 18)]
        elif fid == 'M1':   # engineer task (bottom) down to the CI start event (top)
            pts = [(x1, y1 + 40), (x1, 250), (x2, 250), (x2, y2 - 18)]
        elif fid == 'M2':   # export task (top) up to the investigation task (bottom), same column
            pts = [(x1, y1 - 40), (x2, y2 + 40)]
        else:
            pts = [(x1, y1), (x2, y2)]
        wps = ''.join(f'<di:waypoint x="{round(x)}" y="{round(y)}"/>' for x, y in pts)
        out.append(f'    <bpmndi:BPMNEdge id="{fid}_di" bpmnElement="{fid}">{wps}</bpmndi:BPMNEdge>')
    out.append('  </bpmndi:BPMNPlane></bpmndi:BPMNDiagram>')
    out.append('</definitions>')
    return '\n'.join(out) + '\n'


# ---------------------------------------------------------------- ArchiMate (Open Exchange Format 3.1)
ELEMENTS = [  # (id, xsi:type, name, layer row, column)
    ('a_role_eng', 'BusinessRole', 'Test engineer', 0, 0),
    ('a_role_rev', 'BusinessRole', 'Reviewer', 0, 1),
    ('a_proc', 'BusinessProcess', 'Evidence-based test campaign', 0, 2),
    ('a_obj_spec', 'BusinessObject', 'Specification (use case, activity, requirements, oracle YAML)', 0, 3),
    ('a_obj_ev', 'BusinessObject', 'Verdict and sealed evidence', 0, 4),
    ('a_app_comp', 'ApplicationComponent', 'Specification compiler (oaef_compile.py)', 1, 0),
    ('a_app_sim', 'ApplicationComponent', 'S1 simulator and fault injection', 1, 1),
    ('a_app_col', 'ApplicationComponent', 'Collector (v5_backend.py)', 1, 2),
    ('a_app_eng', 'ApplicationComponent', 'Oracle engine', 1, 3),
    ('a_app_rep', 'ApplicationComponent', 'Report, Allure, export, screenshots', 1, 4),
    ('a_data_con', 'DataObject', 'Oracle contract v3 (60 obligations)', 1, 5),
    ('a_app_graf', 'ApplicationComponent', 'Grafana with Tempo, Loki, Prometheus', 2, 2),
    ('a_tech_run', 'Node', 'GitHub Actions runner', 3, 0),
    ('a_tech_lgtm', 'SystemSoftware', 'grafana/otel-lgtm container (pinned)', 3, 2),
    ('a_tech_pw', 'SystemSoftware', 'Playwright container (pinned)', 3, 3),
    ('a_tech_art', 'Artifact', 'CI artifacts: reports, campaign zip', 3, 4),
]
RELATIONS = [  # (id, xsi:type, source, target)
    ('r1', 'Assignment', 'a_role_eng', 'a_proc'), ('r2', 'Assignment', 'a_role_rev', 'a_proc'),
    ('r3', 'Access', 'a_proc', 'a_obj_spec'), ('r4', 'Access', 'a_proc', 'a_obj_ev'),
    ('r5', 'Access', 'a_app_comp', 'a_obj_spec'), ('r6', 'Realization', 'a_app_comp', 'a_data_con'),
    ('r7', 'Access', 'a_app_eng', 'a_data_con'), ('r8', 'Flow', 'a_app_sim', 'a_app_graf'),
    ('r9', 'Flow', 'a_app_graf', 'a_app_col'), ('r10', 'Flow', 'a_app_col', 'a_app_eng'),
    ('r11', 'Flow', 'a_app_eng', 'a_app_rep'), ('r12', 'Realization', 'a_app_rep', 'a_obj_ev'),
    ('r13', 'Serving', 'a_app_rep', 'a_proc'), ('r14', 'Realization', 'a_tech_lgtm', 'a_app_graf'),
    ('r15', 'Assignment', 'a_tech_run', 'a_tech_lgtm'), ('r16', 'Assignment', 'a_tech_run', 'a_tech_pw'),
    ('r17', 'Serving', 'a_tech_pw', 'a_app_rep'), ('r18', 'Realization', 'a_tech_art', 'a_obj_ev'),
]


def archimate():
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<model xmlns="http://www.opengroup.org/xsd/archimate/3.0/" '
           'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
           'xsi:schemaLocation="http://www.opengroup.org/xsd/archimate/3.0/ http://www.opengroup.org/xsd/archimate/3.1/archimate3_Diagram.xsd" '
           'identifier="id-oaef-v5">',
           '  <name xml:lang="en">OAEF V5 evidence-based testing</name>',
           '  <documentation xml:lang="en">Generated by docs/process/build_process_models.py. Business, application and '
           'technology view of the OAEF V5 campaign; no element of the run path calls a GenAI model.</documentation>',
           '  <elements>']
    for eid, kind, name, _, _ in ELEMENTS:
        out.append(f'    <element identifier="{eid}" xsi:type="{kind}"><name xml:lang="en">{escape(name)}</name></element>')
    out.append('  </elements>\n  <relationships>')
    for rid, kind, s, t in RELATIONS:
        out.append(f'    <relationship identifier="{rid}" source="{s}" target="{t}" xsi:type="{kind}"/>')
    out.append('  </relationships>\n  <views><diagrams>')
    out.append('    <view identifier="v1" xsi:type="Diagram"><name xml:lang="en">OAEF V5 layered view</name>')
    pos = {}
    for eid, _, _, row, col in ELEMENTS:
        x, y = 40 + col * 200, 40 + row * 140
        pos[eid] = f'n_{eid}'
        out.append(f'      <node identifier="n_{eid}" elementRef="{eid}" xsi:type="Element" x="{x}" y="{y}" w="170" h="70"/>')
    for rid, _, s, t in RELATIONS:
        out.append(f'      <connection identifier="c_{rid}" relationshipRef="{rid}" xsi:type="Relationship" '
                   f'source="{pos[s]}" target="{pos[t]}"/>')
    out.append('    </view>\n  </diagrams></views>\n</model>')
    return '\n'.join(out) + '\n'


if __name__ == '__main__':
    for name, text in (('oaef-v5-campaign.bpmn', bpmn()), ('oaef-v5-archimate.xml', archimate())):
        (HERE / name).write_text(text, encoding='utf-8', newline='\n')
        print('wrote', HERE / name)
