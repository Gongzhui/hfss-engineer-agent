"""Read report settings from trace objects, where AEDT actually stores them."""

REPORT_DETAILS_SCRIPT = r'''
module = oDesign.GetModule('ReportSetup')
rpt = module.GetChildObject(report_name)
result['solution_data'] = str(rpt.GetPropValue('Report Type'))
result['display_type'] = str(rpt.GetPropValue('Display Type'))
result['prop_names'] = list(rpt.GetPropNames(True))
result['trace_details'] = []
for name in rpt.GetChildNames():
    obj = rpt.GetChildObject(name)
    props = list(obj.GetPropNames(True))
    if 'Y Component' not in props:
        continue
    item = {'name': str(name), 'families': {}}
    for prop, key in [('Solution', 'solution'), ('Domain', 'domain'),
                      ('Primary Sweep', 'primary_sweep'), ('X Component', 'x_component'),
                      ('Y Component', 'expression'), ('Context', 'context')]:
        if prop in props:
            item[key] = obj.GetPropValue(prop)
    if 'Families' in props:
        raw = obj.GetPropValue('Families')
        while len(raw) == 1 and isinstance(raw[0], (list, tuple)):
            raw = raw[0]
        for i in range(0, len(raw), 2):
            item['families'][str(raw[i]).replace(':=', '')] = list(raw[i + 1])
    result['trace_details'].append(item)
'''
