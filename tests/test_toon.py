import unittest
from tools.common.toon import encode, dumps, format_primitive


class MockModel:
    def __init__(self, data):
        self.data = data

    def to_dict(self):
        return self.data


class TestToonEncoder(unittest.TestCase):
    def test_primitives(self):
        self.assertEqual(encode(None), "null")
        self.assertEqual(encode(True), "true")
        self.assertEqual(encode(False), "false")
        self.assertEqual(encode(42), "42")
        self.assertEqual(encode(3.14), "3.14")
        self.assertEqual(encode(1.0), "1")
        self.assertEqual(encode("hello"), "hello")
        # Strings requiring quotes
        self.assertEqual(encode(""), '""')
        self.assertEqual(encode("hello, world"), '"hello, world"')
        self.assertEqual(encode("key: value"), '"key: value"')
        self.assertEqual(encode("true"), '"true"')
        self.assertEqual(encode("123"), '"123"')
        self.assertEqual(encode("# comment"), '"# comment"')

    def test_empty_structures(self):
        self.assertEqual(encode([]), "[]")
        self.assertEqual(encode({}), "")
        self.assertEqual(encode({"items": []}), "items: []")
        self.assertEqual(encode({"config": {}}), "config:")

    def test_simple_object(self):
        data = {
            "name": "Edge Plugin",
            "version": 1,
            "active": True,
        }
        expected = "name: Edge Plugin\nversion: 1\nactive: true"
        self.assertEqual(encode(data), expected)

    def test_inline_array(self):
        data = {
            "tags": ["alpha", "beta", "gamma"],
            "scores": [10, 20, 30],
        }
        expected = "tags[3]: alpha,beta,gamma\nscores[3]: 10,20,30"
        self.assertEqual(encode(data), expected)

    def test_tabular_array(self):
        data = {
            "users": [
                {"id": 1, "name": "Ada", "role": "admin"},
                {"id": 2, "name": "Bob", "role": "user"},
            ]
        }
        expected = "users[2]{id,name,role}:\n  1,Ada,admin\n  2,Bob,user"
        self.assertEqual(encode(data), expected)

    def test_tabular_with_nested_field_groups(self):
        data = {
            "forecast": [
                {"day": "Mon", "temp": {"min": -2, "max": 4}, "condition": "snow"},
                {"day": "Tue", "temp": {"min": 1, "max": 7}, "condition": "cloudy"},
            ]
        }
        expected = "forecast[2]{day,temp{min,max},condition}:\n  Mon,-2,4,snow\n  Tue,1,7,cloudy"
        self.assertEqual(encode(data), expected)

    def test_keyed_tabular(self):
        data = {
            "environments": {
                "production": {"region": "eu-central-1", "replicas": 6, "debug": False},
                "staging": {"region": "eu-central-1", "replicas": 2, "debug": True},
            }
        }
        expected = (
            "environments[2:]{region,replicas,debug}:\n"
            "  production: eu-central-1,6,false\n"
            "  staging: eu-central-1,2,true"
        )
        self.assertEqual(encode(data), expected)

    def test_list_form_fallback(self):
        # Non-uniform objects
        data = {
            "mixed": [
                {"id": 1, "name": "Alice"},
                {"id": 2, "role": "admin"},
            ]
        }
        result = encode(data)
        self.assertTrue(result.startswith("mixed[2]:"))
        self.assertIn("- id: 1", result)
        self.assertIn("- id: 2", result)

    def test_model_with_to_dict(self):
        model = MockModel({
            "ticket": {
                "id": "T-100",
                "domain": "billing",
                "rules": ["rule-1", "rule-2"],
            }
        })
        expected = "ticket:\n  id: T-100\n  domain: billing\n  rules[2]: rule-1,rule-2"
        self.assertEqual(dumps(model), expected)


if __name__ == "__main__":
    unittest.main()
