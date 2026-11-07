from __future__ import annotations
import unittest
from dor.selectors import parse_json_pointer, parse_profile_path, render_json_pointer, select_records

class JsonSelectorTests(unittest.TestCase):
    def test_profile_path_and_pointer_wildcards_align(self):
        profile=parse_profile_path("$['records'][]['a/b~c']")
        pointer=parse_json_pointer("/records/*/a~1b~0c")
        self.assertEqual(profile,pointer)

    def test_pointer_round_trip_escapes(self):
        tokens=("records","a/b","x~y")
        self.assertEqual(parse_json_pointer(render_json_pointer(tokens)),tokens)

    def test_record_selector_returns_concrete_object_pointers(self):
        payload={"papers":[{"results":[{"value":1},{"value":2}]},{"results":[{"value":3}]}]}
        records=select_records(payload,"/papers/*/results/*")
        self.assertEqual([pointer for _,pointer in records],[
            ("papers","0","results","0"),("papers","0","results","1"),("papers","1","results","0")])
        self.assertEqual([record["value"] for record,_ in records],[1,2,3])

    def test_record_selector_requires_array_wildcard(self):
        with self.assertRaises(ValueError):
            select_records({"records":[{"x":1}]},"/records")

    def test_bad_pointer_escape_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_json_pointer("/records/~2bad")

if __name__=="__main__": unittest.main()
