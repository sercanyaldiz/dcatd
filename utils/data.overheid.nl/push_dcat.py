import json
import os
from urllib import request, parse
import pprint
from pyld import jsonld

from datacatalog.plugins import dcat_ap_ams


def _get_request_with_headers(url):
    headers = {
        "accept": "application/json",
        "accept-charset": "utf-8",
        "user-agent": "Deliberately empty"
    }
    req = request.Request(url)
    for key, val in headers.items():
        req.add_header(key, val)
    return req

def push_dcat():
    dcat_env = os.getenv('ENVIRONMENT', 'acc')  # acc or prod
    api_key = os.getenv('API_KEY')
    organisation_id = os.getenv('ORGANISATION_ID')

    dcat_root = 'https://api.data.amsterdam.nl' if dcat_env == 'prod' else 'https://acc.api.data.amsterdam.nl'
    donl_root = 'https://data.overheid.nl/data' if dcat_env == 'prod' else 'http://beta-acc.data.overheid.nl/data'

    context = dcat_ap_ams.context()

    req = _get_request_with_headers(f'{dcat_root}/datasets')

    with request.urlopen(req) as response:
        assert 200 == response.getcode()
        datasets = json.load(response)

    datasets = jsonld.compact(datasets, context)
    print(json.dumps(datasets, indent=2))

    count = 0
    for dataset_iterator in datasets['dcat:dataset']:
        req = _get_request_with_headers(dataset_iterator['@id'])
        with request.urlopen(req) as response:
            assert 200 == response.getcode()
            dataset = json.load(response)
        dataset = jsonld.compact(dataset, context)

        if not api_key:
            continue

        count += 1
        if count > 1:
            break

        # check if dataset exists

        id = dataset['@id']

        # TODO convert dataset to DCAT 1.1 standards
        data_string = parse.quote(json.dumps(dataset))

        action = 'package_show'
        req = _get_request_with_headers(f'{donl_root}/api/3/action/{action}?id={id}')
        response = request.urlopen(req)
        assert response.code == 200
        response_dict1 = json.loads(response.read())
        if response_dict1['success'] is True:
            # Dataset already exists. Use package_update
            action = 'package_update'
            req = _get_request_with_headers(f'{donl_root}/api/3/action/{action}?id={id}', data_string)
            response = request.urlopen(req)
            assert response.code == 200
            response_dict2 = json.loads(response.read())
            updated_package = response_dict2['result']
            pprint.pprint(updated_package)
        else:
            # Dataset does not exist . Use package_create
            action = 'package_create'
            req = _get_request_with_headers(f'{donl_root}/api/3/action/{action}', data_string)
            response = request.urlopen(req)
            assert response.code == 200
            response_dict3 = json.loads(response.read())
            created_package = response_dict3['result']
            pprint.pprint(created_package)


if __name__ == '__main__':
    push_dcat()

