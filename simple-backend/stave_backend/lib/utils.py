import json
from typing import Dict, Literal, Optional, List
from packaging.version import Version
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, get_list_or_404
from django.forms import model_to_dict
from ..models import Document, Project, Job

def check_perm_project(project, user, perm):
    if not user.has_perm(perm, project) and user != project.user:
        raise PermissionDenied

def fetch_doc_check_perm(id, user, perm):
    """Fetches a document by id and check the permission.
    
    Fetches a document by id and check whether the user has certain permission.

    Args:
        document_id:
            The id of the document.
        user:
            A User instance.
        perm:
            Permission to check. Example: "stave_backend.read_project"

    Returns:
        A json response of the or forbidden or not found.
        example:

            {"id": 42, "name": "project1-doc1-example", "project_id": 5, "textPack": "...", ...}    
    """
    doc = get_object_or_404(Document, pk=id)
    
    check_perm_project(doc.project, user, perm)

    return doc

def fetch_project_check_perm(id, user, perm):
    """Fetches a project by id and check the permission.
    
    Fetches a project by id and check whether the user has certain permission.

    Args:
        project_id:
            The id of the project.
        user:
            A User instance.
        perm:
            Permission to check. Example: "stave_backend.read_project"
            
    Returns:
        A json response of the or forbidden or not found.
        
    """
    project = get_object_or_404(Project, pk=id)
    
    check_perm_project(project, user, perm)

    return project

def fetch_job(user):
    """Fetches a job by id and check the permission.
    
    Fetches a job by id and check whether the user has certain permission.

    Args:
        user:
            A User instance.
            
    Returns:
        A json response of the or forbidden or not found.
        
    """
    jobs = get_list_or_404(Job, assignee=user)

    return jobs

def transform_pack(raw_pack: str, raw_ontology: str):
    pack_json: Dict = json.loads(raw_pack)["py/state"]
    onto_defs: OntoDefinitions = OntoDefinitions(raw_ontology=raw_ontology)

    annotations, links, groups = [], [], []
    if Version(
        pack_json.get("pack_version", "0.0.0")
    ) < Version("0.0.2"):
        # Parse the previous version
        for annotation in pack_json["annotations"]:
            entry_data: Dict = annotation.get("py/state")
            if not entry_data: continue
            annotations.append({
                "span": {
                    "begin": entry_data["_span"]["begin"],
                    "end": entry_data["_span"]["end"],
                    },
                "id": str(entry_data["_tid"]),
                "legendId": annotation.get("py/object"),
                "attributes": onto_defs.get_attributes(annotation),
            })
        for link in pack_json["links"]:
            entry_data: Dict = link.get("py/state")
            if not entry_data: continue
            links.append({
                "id": str(entry_data["_tid"]),
                "fromEntryId": str(entry_data["_parent"]),
                "toEntryId": str(entry_data["_child"]),
                "legendId": link.get("py/object"),
                "attributes": onto_defs.get_attributes(link),
            })
        for group in pack_json["groups"]:
            entry_data: Dict = group.get("py/state")
            if not entry_data: continue
            groups.append({
                "id": str(entry_data["_tid"]),
                "members": [str(tid) for tid in entry_data["_members"]["py/set"]],
                "memberType": onto_defs.get_group_type(group.get("py/object")),
                "legendId": group.get("py/object"),
                "attributes": onto_defs.get_attributes(group),
            })
    else:
        # Parse the new version
        fields: Dict = pack_json["_data_store"]["py/state"]["fields"]
        for entry_type, entry_list in pack_json["_data_store"]["py/state"]["entries"].items():
            parent_type = onto_defs.get_entry_type(entry_type)
            if parent_type not in (
                onto_defs.ANNOTATION, onto_defs.LINK, onto_defs.GROUP
            ):
                continue

            for entry_data in entry_list:
                attributes: Dict = {
                    attr_name: entry_data[attr_ind]
                    for attr_name, attr_ind in fields[entry_type]['attributes'].items()
                }
                if parent_type == onto_defs.ANNOTATION:
                    annotations.append({
                        "span": {
                            "begin": entry_data[0],
                            "end": entry_data[1],
                        },
                        "id": str(entry_data[2]),
                        "legendId": entry_data[3],
                        "attributes": attributes,
                    })
                elif parent_type == onto_defs.LINK:
                    links.append({
                        "id": str(entry_data[2]),
                        "fromEntryId": str(entry_data[0]),
                        "toEntryId": str(entry_data[1]),
                        "legendId": entry_data[3],
                        "attributes": attributes,
                    })
                elif parent_type == onto_defs.GROUP:
                    groups.append({
                        "id": str(entry_data[2]),
                        "members": [str(tid) for tid in entry_data[1]],
                        "memberType": onto_defs.get_group_type(entry_data[3]),
                        "legendId": entry_data[3],
                        "attributes": attributes,
                    })
    return {
        "text": pack_json["_text"],
        "annotations": annotations,
        "links": links,
        "groups": groups,
        "attributes":
        # Backward compatibility with Forte formats.
        pack_json["meta"]["py/state"] if "meta" in pack_json else pack_json["_meta"]["py/state"],
    }

def add_entry_to_doc(doc: Document, entry: Dict):
    doc_json: Dict = model_to_dict(doc)
    pack_json: Dict = json.loads(doc_json['textPack'])
    onto_defs: OntoDefinitions = OntoDefinitions(raw_ontology=doc.project.ontology)

    entry_type: str = entry["py/object"]
    parent_type = onto_defs.get_entry_type(entry_type)
    if Version(
        pack_json['py/state'].get("pack_version", "0.0.0")
    ) < Version("0.0.2"):
        list_name: str = ''
        if parent_type == onto_defs.ANNOTATION:
            list_name = "annotations"
        elif parent_type == onto_defs.LINK:
            list_name = "links"
        if list_name:
            pack_json['py/state'][list_name].append(entry)
    else:
        fields: Dict = pack_json["py/state"]["_data_store"]["py/state"]["fields"]
        if entry_type not in fields:
            fields[entry_type] = {"attributes": {
                attr_name: 4 + i
                for i, attr_name in enumerate(
                    list(onto_defs.get_attribute_names(entry_type))
                )
            }}
        attr_index_map: Dict = fields[entry_type]["attributes"]
        new_entry: List = []
        if parent_type == onto_defs.ANNOTATION:
            new_entry = [
                entry["py/state"]["_span"]["begin"],
                entry["py/state"]["_span"]["end"],
                entry["py/state"]["_tid"],
                entry_type,
            ]
        elif parent_type == onto_defs.LINK:
            new_entry = [
                entry["py/state"]["_parent"],
                entry["py/state"]["_child"],
                entry["py/state"]["_tid"],
                entry_type,
            ]
        new_entry += [None] * len(attr_index_map)
        for attr_name, attr_val in entry["py/state"].items():
            if attr_name in attr_index_map:
                new_entry[attr_index_map[attr_name]] = attr_val

        entries: Dict = pack_json["py/state"]["_data_store"]["py/state"]["entries"]
        if entry_type not in entries:
            entries[entry_type] = []
        entries[entry_type].append(new_entry)

    doc.textPack = json.dumps(pack_json)
    doc.save()

def edit_entry_in_doc(doc: Document, entry: Dict):
    doc_json: Dict = model_to_dict(doc)
    pack_json: Dict = json.loads(doc_json['textPack'])
    onto_defs: OntoDefinitions = OntoDefinitions(raw_ontology=doc.project.ontology)

    entry_type: str = entry["py/object"]
    parent_type = onto_defs.get_entry_type(entry_type)
    if Version(
        pack_json['py/state'].get("pack_version", "0.0.0")
    ) < Version("0.0.2"):
        list_name: str = ''
        if parent_type == onto_defs.ANNOTATION:
            list_name = "annotations"
        elif parent_type == onto_defs.LINK:
            list_name = "links"
        if list_name:
            for index, item in enumerate(pack_json['py/state'][list_name]):
                if str(item["py/state"]['_tid']) == str(entry["py/state"]['_tid']):
                    pack_json['py/state'][list_name][index] = entry
    else:
        entries: Dict = pack_json["py/state"]["_data_store"]["py/state"]["entries"]
        for index, item in enumerate(entries[entry_type]):
            if str(item["py/state"]['_tid']) == str(entry["py/state"]['_tid']):
                entries[entry_type][index] = entry

    doc.textPack = json.dumps(pack_json)
    doc.save()

def delete_entry_from_doc(
    doc: Document, entry_tid: str, parent_type: Literal["annotation", "link"]
):
    doc_json: Dict = model_to_dict(doc)
    pack_json: Dict = json.loads(doc_json['textPack'])
    onto_defs: OntoDefinitions = OntoDefinitions(raw_ontology=doc.project.ontology)

    delete_index = -1
    if Version(
        pack_json['py/state'].get("pack_version", "0.0.0")
    ) < Version("0.0.2"):
        list_name: str = ''
        if parent_type == onto_defs.ANNOTATION:
            list_name = "annotations"
        elif parent_type == onto_defs.LINK:
            list_name = "links"
        if list_name:
            for index, item in enumerate(pack_json['py/state'][list_name]):
                if str(item["py/state"]['_tid']) == str(entry_tid):
                    delete_index = index
            if delete_index >= 0:
                del pack_json['py/state'][list_name][delete_index]
    else:
        entries: Dict = pack_json["py/state"]["_data_store"]["py/state"]["entries"]
        for entry_name, entry_list in entries.items():
            if onto_defs.get_entry_type(entry_name) != parent_type:
                continue
            for index, item in enumerate(entry_list):
                if str(item[2]) == str(entry_tid):
                    delete_index = index
            if delete_index >= 0:
                del entries[entry_name][delete_index]

    doc.textPack = json.dumps(pack_json)
    doc.save()


class OntoDefinitions:

    ANNOTATION = "annotation"
    LINK = "link"
    GROUP = "group"
    UNKNOWN = "unknown"

    def __init__(self, raw_ontology: str) -> None:
        self._entries: Dict = {
            definition["entry_name"]: definition
            for definition in json.loads(raw_ontology).get("definitions", [])
        }

    def _is_parent_match(self, entry_name: str, match_name: str):
        if entry_name == match_name: return True
        parent_entry: str = self._entries.get(entry_name, {}).get("parent_entry")
        if not parent_entry: return False
        return self._is_parent_match(parent_entry, match_name)

    def get_attribute_names(self, entry_name: str) -> set:
        definition: Optional[Dict] = self._entries.get(entry_name)
        if not definition or not definition.get("attributes"):
            return set()
        return set(attr_obj["name"] for attr_obj in definition["attributes"])

    def get_attributes(self, entry: Dict):
        attr_set = self.get_attribute_names(entry["py/object"])
        return {
            attr_name: attr_val
            for attr_name, attr_val in entry["py/state"].items()
            if attr_name in attr_set
        }

    def get_entry_type(self, entry_name: str):
        if self._is_parent_match(entry_name, "forte.data.ontology.top.Annotation"):
            return self.ANNOTATION
        elif self._is_parent_match(entry_name, "forte.data.ontology.top.Link"):
            return self.LINK
        elif self._is_parent_match(entry_name, "forte.data.ontology.top.Group"):
            return self.GROUP
        else:
            return self.UNKNOWN

    def get_group_type(self, entry_name: str):
        entry_type: str = self.get_entry_type(
            self._entries.get(entry_name, {}).get("member_type")
        )
        if entry_type == self.ANNOTATION:
            return "annotation"
        elif entry_type == self.LINK:
            return "link"
        else:
            raise ValueError(f"Unknown group entry: {entry_name}")
