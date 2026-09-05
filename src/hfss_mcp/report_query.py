# ruff: noqa: E501
"""IronPython probe of a report's actual selections, not the GUI cross state.

GetSolutionDataPerVariation can retain data after Setup edits in AEDT 2023 R2.
Successful retrieval must never be advertised as full solution validity.
"""

REPORT_QUERY_SCRIPT = r"""
report_module = oDesign.GetModule('ReportSetup')
rpt = report_module.GetChildObject(report_name)
status = {'data_availability': 'not_checked', 'validity': 'unknown',
          'source': 'GetSolutionDataPerVariation', 'traces': [],
          'reason': 'Data availability does not certify current geometry/material/Setup validity'}
result['solution_status'] = status
if str(rpt.GetPropValue('Report Type')) == 'Modal Solution Data':
    requests = []
    for child in rpt.GetChildNames():
        trace = rpt.GetChildObject(child)
        props = list(trace.GetPropNames(True))
        if 'Y Component' not in props:
            continue
        if str(trace.GetPropValue('Primary Sweep')) != 'Freq':
            requests = []
            break
        if 'Domain' not in props or str(trace.GetPropValue('Domain')) != 'Sweep':
            requests = []
            break
        # Read each trace, including user edits made after MCP report_create.
        selected = {}
        if 'Families' in props:
            raw = trace.GetPropValue('Families')
            while len(raw) == 1 and isinstance(raw[0], (list, tuple)):
                raw = raw[0]
            for i in range(0, len(raw), 2):
                selected[str(raw[i]).replace(':=', '')] = list(raw[i + 1])
        requested = {}
        for var in oDesign.GetVariables():
            requested[str(var)] = [str(oDesign.GetVariableValue(var))]
        for var in oProject.GetVariables():
            requested[str(var)] = [str(oProject.GetVariableValue(var))]
        for var, values in selected.items():
            if values != ['Nominal']:
                requested[var] = values
            elif var not in requested:
                requests = []
                break
        else:
            requested['Freq'] = ['All']
            families = []
            for var, values in requested.items():
                families += [var + ':=', values]
            requests.append((str(child), str(trace.GetPropValue('Solution')),
                             str(trace.GetPropValue('Y Component')), families, requested))
            continue
        break
    if requests:
        status['data_availability'] = 'available'
        for child, solution, expression, families, requested in requests:
            try:
                data = report_module.GetSolutionDataPerVariation(
                    'Modal Solution Data', solution, ['Domain:=', 'Sweep'], families, [expression])
                if not data:
                    raise Exception('No data returned for the selected solution and Families')
                records = []
                for item in data:
                    vals = item.GetRealDataValues(expression)
                    if not vals:
                        raise Exception('Empty data returned for ' + expression)
                    names = list(item.GetDesignVariableNames())
                    records.append({'variation_key': item.GetDesignVariationKey(),
                                    'variables_si': {str(n): item.GetDesignVariableValue(n) for n in names},
                                    'points': len(vals)})
                status['traces'].append({'trace': child, 'solution': solution,
                                         'expression': expression, 'requested_families': requested,
                                         'variations': records[:256], 'variation_count': len(records),
                                         'variations_truncated': len(records) > 256})
            except Exception as error:
                status['data_availability'] = 'query_failed'
                status['query_error'] = str(error)
                break
        if status['data_availability'] == 'available':
            # Refresh the report cache using its existing selections. No solve.
            report_module.UpdateReports([report_name])
            status['report_refreshed'] = True
"""
