import copy
import json
import logging
import os
from functools import reduce

import yaml
from aiopluggy import HookimplMarker
from pkg_resources import resource_stream
from whoosh.analysis import StemmingAnalyzer
from whoosh.fields import Schema, ID, TEXT
from whoosh.index import create_in
from whoosh.qparser import QueryParser
from whoosh.query import Variations

from attic.src.datacatalog.handlers import action_api

log = logging.getLogger(__name__)
hook = HookimplMarker('datacatalog')


def _init_or_increment(dictionary, key):
    if key in dictionary:
        dictionary[key] += 1
    else:
        dictionary[key] = 1


def _matcher(key, value):
    def _reduce_function(seed, dictionary):
        return seed or value is None or dictionary[key] == value
    return _reduce_function


class InMemorySearchPlugin(object):

    def __init__(self):
        self.FILEDATA_DIRECTORY = None
        self.FILEDATA = None
        self.all_packages = None
        self.index = None

    @hook
    def initialize(self, app):
        with resource_stream(__name__, 'in_memory_search_config_schema.yml') as s:
            schema = yaml.load(s)
        app.config.validate(schema)

        search_config = app.config['inmemorysearch']
        self.FILEDATA_DIRECTORY = search_config['path']
        self.FILEDATA = os.path.join(self.FILEDATA_DIRECTORY, search_config['all_packages'])

        if os.path.exists(self.FILEDATA):
            with open(self.FILEDATA) as json_data:
                self.all_packages = json.load(json_data)

            """
                REMARK: This bit for freetext search is orthogonal, can be factored out in the future
            """
            stemming_analyzer = StemmingAnalyzer()
            schema = Schema(nid=ID(stored=True),
                            title=TEXT(analyzer=stemming_analyzer),
                            notes=TEXT(analyzer=stemming_analyzer))
            index_path = os.path.join(self.FILEDATA_DIRECTORY, "whoosh_index")
            if not os.path.exists(index_path):
                os.mkdir(index_path)
            self.index = create_in(index_path, schema)

            writer = self.index.writer()
            for document in self.all_packages['result']['results']:
                writer.add_document(nid=document['id'], title=document['title'], notes=document['notes'])
            writer.commit()

    @hook
    def health_check(self):
        return self._health_check()

    def _health_check(self):
        if not os.path.exists(self.FILEDATA):
            return self.__class__

    def _fulltext_search_ids(self, query):
        qp = QueryParser("notes", termclass=Variations, schema=self.index.schema)
        q = qp.parse(query[action_api.SearchParam.QUERY])
        qp = QueryParser("title", termclass=Variations, schema=self.index.schema)
        q1 = qp.parse(query[action_api.SearchParam.QUERY])
        with self.index.searcher() as searcher:
            results = searcher.search(q, limit=None)
            results1 = searcher.search(q1, limit=None)
            return [result['nid'] for result in results] + \
                   [result['nid'] for result in results1]

    def _result_matches_facets(self, result, query):
        if action_api.SearchParam.FACET_QUERY not in query:
            return True

        facets = query[action_api.SearchParam.FACET_QUERY]

        if action_api.Facet.GROUP.value in facets:
            match_function = _matcher('name', facets[
                action_api.Facet.GROUP.value])
            group_match = reduce(match_function, result['groups'], False)
            if not group_match:
                return False

        if action_api.Facet.RESOURCE.value in facets:
            match_function = _matcher('format', facets[
                action_api.Facet.RESOURCE.value])
            resource_match = reduce(match_function, result['resources'], False)
            if not resource_match:
                return False

        if action_api.Facet.PUBLISHER.value in facets:
            if (
                    result['organization'] is None or
                    result['organization']['name'] != facets[
                        action_api.Facet.PUBLISHER.value
                    ]
            ):
                return False

        return True

    def _get_empty_facets(self):
        return {facet.value: {} for facet in action_api.Facet}

    def _get_empty_search_facets(self):
        return {
            facet.value: {"items": [], "title": facet.value}
            for facet in action_api.Facet
        }

    def _get_facets(self, facets, result):
        if result['organization'] is not None:
            _init_or_increment(facets['organization'], result['organization']['name'])

        for resource in result['resources']:
            _init_or_increment(facets['res_format'], resource['format'])

        for group in result['groups']:
            _init_or_increment(facets['groups'], group['name'])

        return facets

    def _add_to_items_or_increment(self, items, candidate_item, name_key, title_key):
        for item in items["items"]:
            if item["name"] == candidate_item[name_key]:
                item["count"] += 1
                return

        items["items"].append({
            "count": 1,
            "display_name": candidate_item[title_key],
            "name": candidate_item[name_key]
        })

    def _get_search_facets(self, search_facets, result):
        if result['organization'] is not None:
            self._add_to_items_or_increment(search_facets['organization'],
                                            result['organization'], "name", "title")

        for resource in result['resources']:
            self._add_to_items_or_increment(search_facets['res_format'], resource, "format", "format")

        for group in result['groups']:
            self._add_to_items_or_increment(search_facets['groups'], group, "name", "name")

        return search_facets

    @hook
    def search_search(self, query=None):
        """Search packages (datasets) that match the query.

        Query can contain freetext search, drilldown on facets and can specify which facets to return

        This specific implemantation doesn't seperate searching, and constructing the resulting object.
        In the future these need to be seperated, and made pluggable.

        :param query:
        :return:

        """
        if query is None:
            query = {}
        results = copy.deepcopy(self.all_packages)

        # filter results for freetext query
        if action_api.SearchParam.QUERY in query:
            matching_ids = self._fulltext_search_ids(query)
            filtered_results = [
                result for result in results['result']['results'] if result['id'] in matching_ids
            ]
        else:
            filtered_results = results['result']['results']

        # filter results for faceted search
        filtered_results = [
            result for result in filtered_results if self._result_matches_facets(result, query)
        ]

        # update metadata
        results['result']['results'] = filtered_results
        results['result']['count'] = len(filtered_results)

        # update facets
        results['result']['facets'] = reduce(self._get_facets,
                                             filtered_results,
                                             self._get_empty_facets())
        results['result']['search_facets'] = reduce(self._get_search_facets,
                                                    filtered_results,
                                                    self._get_empty_search_facets())

        # filter facets based on requested facets
        if action_api.SearchParam.FACET_FIELDS in query:
            results['result']['facets'] = {k: v for k, v in results['result']['facets'].items()
                                           if k in query[
                                               action_api.SearchParam.FACET_FIELDS]}
            results['result']['search_facets'] = {k: v for k, v in results['result']['search_facets'].items()
                                                  if k in query[
                                                      action_api.SearchParam.FACET_FIELDS]}

        # apply paging
        begin = query[action_api.SearchParam.START] \
            if action_api.SearchParam.START in query else 0
        if action_api.SearchParam.ROWS in query:
            end = begin + query[action_api.SearchParam.ROWS]
            results['result']['results'] = results['result']['results'][begin:end]
        else:
            results['result']['results'] = results['result']['results'][begin:]

        return results


plugin = InMemorySearchPlugin()