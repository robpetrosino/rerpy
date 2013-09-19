# This file is part of pyrerp
# Copyright (C) 2013 Nathaniel Smith <njs@pobox.com>
# See file COPYING for license information.

import numpy as np
import pandas
from nose.tools import assert_raises

from pyrerp.data import DataSet, DataFormat, mock_dataset

class MockDataSource(object):
    def __init__(self, tick_lengths):
        self._tick_lengths = tick_lengths
        self._transform = np.eye(2)

    def __getitem__(self, local_recspan_id):
        ticks = self._tick_lengths[local_recspan_id]
        return np.dot(np.ones((ticks, 2)) * local_recspan_id,
                      self._transform.T)

    def transform(self, matrix):
        self._transform = np.dot(matrix, self._transform)

    def copy(self):
        new = MockDataSource(self._tick_lengths)
        new.transform(self._transform)
        return new

def test_DataSet():
    data_format = DataFormat(250, "uV", ["MOCK1", "MOCK2"])
    dataset = DataSet(data_format)

    assert len(dataset) == 0
    assert_raises(IndexError, dataset.__getitem__, 0)
    assert_raises(TypeError, dataset.__getitem__, slice(0, 0))
    assert list(dataset) == []

    # Mismatch between tick_lengths and metadatas
    assert_raises(ValueError, dataset.add_recspan_source,
                  MockDataSource([10, 20]), [10, 20], [{}])
    dataset.add_recspan_source(MockDataSource([10, 20]),
                                [10, 20],
                                [{"a": 0}, {"a": 1}])
    dataset.add_recspan_source(MockDataSource([30, 40]),
                                [30, 40],
                                [{"a": 2}, {"a": 3}])
    assert len(dataset) == 4
    assert_raises(IndexError, dataset.__getitem__, 4)

    dataset.add_event(1, 10, 11, {"foo": "bar"})

    def t(ds, recspan_id, expected_values=None):
        recspan = ds[recspan_id]
        assert isinstance(recspan, pandas.DataFrame)
        expected_ticks = 10 * (recspan_id + 1)
        assert recspan.shape == (expected_ticks, 2)
        # 1/250 Hz = 4.0 ms
        assert np.all(recspan.index == np.arange(expected_ticks) * 4.0)
        # index is supposed to be floats. Not sure if that means float or
        # np.float64, but this check should work for either:
        assert isinstance(recspan.index[0], float)
        assert np.all(recspan.columns == ["MOCK1", "MOCK2"])
        # Values are supposed to be floating point as well.
        assert type(recspan.iloc[0, 0]) is np.float64
        if expected_values is None:
            local_recspan_id = recspan_id % 2
            expected_values = local_recspan_id
        assert np.allclose(recspan, expected_values)

        assert ds.recspan_infos[recspan_id]["a"] == recspan_id
        assert ds.recspan_infos[recspan_id].ticks == expected_ticks

    for i in xrange(4):
        t(dataset, i)

    # DataFormat mismatch
    diff_dataset = DataSet(DataFormat(500, "uV", ["MOCK1", "MOCK2"]))
    assert_raises(ValueError, diff_dataset.add_dataset, dataset)

    dataset_copy = DataSet(data_format)
    dataset_copy.add_dataset(dataset)
    assert len(dataset_copy) == 4
    for i in xrange(4):
        t(dataset_copy, i)
    assert len(dataset_copy.events()) == 1
    assert dict(dataset_copy.events()[0]) == {"foo": "bar"}
    assert dataset_copy.events()[0].recspan_id == 1

    assert_raises(ValueError, dataset.transform, np.eye(2), exclude=["MOCK1"])
    dataset.transform([[2, 0], [0, 3]])
    # Transforming the first data set doesn't affect the second
    for i in xrange(4):
        t(dataset_copy, i)
    # But it does affect the first!
    for i in xrange(4):
        t(dataset, i, expected_values=[[2 * (i % 2), 3 * (i % 2)]])
    # Try a symbolic transform too -- it should stack with the previous
    # transform.
    dataset.transform("-MOCK1/3", exclude=["MOCK1"])
    for i in xrange(4):
        t(dataset, i, expected_values=[[2 * (i % 2),
                                         3 * (i % 2) - (2./3) * (i % 2)]])

    # Also check that changing one DataSet's metadata doesn't affect the copy.
    dataset.recspan_infos[0]["a"] = 100
    assert dataset.recspan_infos[0]["a"] == 100
    assert dataset_copy.recspan_infos[0]["a"] == 0
    # Set it back to avoid any confusion later in the test
    dataset.recspan_infos[0]["a"] = 0

    # Check __iter__
    recspans = list(dataset)
    assert len(recspans) == 4
    for i in xrange(4):
        assert np.all(recspans[i] == dataset[i])

def test_DataSet_add_recspan():
    # Check the add_recspan convenience method
    dataset = mock_dataset(num_channels=2, num_recspans=4)
    dataset.add_recspan([[1, 2], [3, 4], [5, 6]], {"a": 31337})
    assert len(dataset) == 5
    assert np.all(dataset[4].columns == ["MOCK0", "MOCK1"])
    assert np.all(dataset[4].index == [0.0, 4.0, 8.0])
    assert np.all(np.asarray(dataset[4]) == [[1, 2], [3, 4], [5, 6]])
    assert type(dataset[4].iloc[0, 0]) is np.float64
    assert dataset.recspan_infos[4]["a"] == 31337

    # Wrong number of channels
    assert_raises(ValueError,
                  dataset.add_recspan, [[1, 2, 3], [4, 5, 6]], {})

def test_DataSet_events():
    # Thorough tests are in test_events; here we just make sure the basic API
    # is functioning.
    dataset = mock_dataset()
    e1 = dataset.add_event(1, 10, 15, {"a": 1, "b": "foo", "c": False})
    e2 = dataset.add_event(2, 12, 17, {"a": 2, "b": "foo", "c": True})

    assert isinstance(dataset.events(), list)

    for args, expected in [((), [e1, e2]),
                           (("_START_TICK == 10",), [e1]),
                           ]:
        assert dataset.events(*args) == expected
        assert len(dataset.events_query(*args)) == len(expected)
        assert list(dataset.events_query(*args)) == expected

    for args, kwargs, expected in [((1, 13), {}, [e1]),
                                   ((2, 13), {}, [e2]),
                                   ((1, 13), {"subset": "a == 2"}, []),
                                   ((1, 8, 12), {}, [e1]),
                                   ]:
        assert dataset.events_at(*args, **kwargs) == expected
        assert len(dataset.events_at_query(*args, **kwargs)) == len(expected)
        assert list(dataset.events_at_query(*args, **kwargs)) == expected

    p = dataset.placeholder_event()
    assert list(p["a"] == 2) == [e2]
    assert dataset.events(p["a"] == 2) == [e2]

# Use this to make sure your DataSource's .transform() and .copy() methods
# work.
def check_transforms(dataset):
    saved_datas = []
    for data in dataset:
        saved_datas.append(np.array(data))
    tr1 = np.eye(dataset.data_format.num_channels)
    tr1[0, 0] = 2
    tr1[0, 1] = -0.5
    dataset.transform(tr1)
    for saved_data, data in zip(saved_datas, dataset):
        assert np.allclose(np.dot(saved_data, tr1.T), data)

    dataset_copy = DataSet(dataset.data_format)
    for saved_data, copy_data in zip(saved_datas, dataset_copy):
        assert np.allclose(np.dot(saved_data, tr1.T), copy_data)

    tr2 = np.eye(dataset.data_format.num_channels)
    tr2[-1, -1] = -3
    tr2[1, 0] = 2.5
    dataset.transform(tr2)

    for saved_data, copy_data in zip(saved_datas, dataset_copy):
        assert np.allclose(np.dot(saved_data, tr1.T), copy_data)

    tr_both = np.dot(tr2, tr1)
    for saved_data, data in zip(saved_datas, dataset):
        assert np.allclose(np.dot(saved_data, tr_both.T), data)

def test_MemoryDataSource_transforms():
    check_transforms(mock_dataset())

def test_DataSet_merge_df():
    def make_events():
        ds = mock_dataset()
        ev1 = ds.add_event(0, 10, 11, {"code": 10, "code2": 20})
        ev2 = ds.add_event(0, 20, 21, {"code": 10, "code2": 21})
        ev3 = ds.add_event(0, 30, 31, {"code": 11, "code2": 20})
        return ds, ev1, ev2, ev3

    ds, ev1, ev2, ev3 = make_events()
    ds.merge_df(pandas.DataFrame({"code": [10, 11], "foo": ["a", "b"]}),
                on="code")
    assert dict(ev1) == {"code": 10, "code2": 20, "foo": "a"}
    assert dict(ev2) == {"code": 10, "code2": 21, "foo": "a"}
    assert dict(ev3) == {"code": 11, "code2": 20, "foo": "b"}

    ds, ev1, ev2, ev3 = make_events()
    ds.merge_df(pandas.DataFrame({"code": [10, 11], "foo": ["a", "b"]}),
                on=["code"])
    assert dict(ev1) == {"code": 10, "code2": 20, "foo": "a"}
    assert dict(ev2) == {"code": 10, "code2": 21, "foo": "a"}
    assert dict(ev3) == {"code": 11, "code2": 20, "foo": "b"}

    ds, ev1, ev2, ev3 = make_events()
    ds.merge_df(pandas.DataFrame({"code": [10, 11], "foo": ["a", "b"]}),
                on={"code": "code"})
    assert dict(ev1) == {"code": 10, "code2": 20, "foo": "a"}
    assert dict(ev2) == {"code": 10, "code2": 21, "foo": "a"}
    assert dict(ev3) == {"code": 11, "code2": 20, "foo": "b"}

    ds, ev1, ev2, ev3 = make_events()
    ds.merge_df(pandas.DataFrame(
            {"code": [10, 11], "code2": [20, 20], "foo": ["a", "b"]}),
               on=["code", "code2"])
    assert dict(ev1) == {"code": 10, "code2": 20, "foo": "a"}
    assert dict(ev2) == {"code": 10, "code2": 21}
    assert dict(ev3) == {"code": 11, "code2": 20, "foo": "b"}

    # Trying to overwrite existing fields
    ds, ev1, ev2, ev3 = make_events()
    assert_raises(ValueError,
                  ds.merge_df,
                  pandas.DataFrame({"code": [10, 11],
                                    "code2": [20, 20],
                                    "foo": ["a", "b"]}),
                  on=["code"])

    ds, ev1, ev2, ev3 = make_events()
    ds.merge_df(pandas.DataFrame({"THECODE": [10, 11], "foo": ["a", "b"]}),
                on={"THECODE": "code"})
    assert dict(ev1) == {"code": 10, "code2": 20, "foo": "a"}
    assert dict(ev2) == {"code": 10, "code2": 21, "foo": "a"}
    assert dict(ev3) == {"code": 11, "code2": 20, "foo": "b"}

    ds, ev1, ev2, ev3 = make_events()
    ds.merge_df(
        pandas.DataFrame({"code": [20, 21, 20],
                          "code2": [10, 10, 11],
                          "foo": ["a", "b", "c"]}),
        on={"code": "code2", "code2": "code"})
    assert dict(ev1) == {"code": 10, "code2": 20, "foo": "a"}
    assert dict(ev2) == {"code": 10, "code2": 21, "foo": "b"}
    assert dict(ev3) == {"code": 11, "code2": 20, "foo": "c"}

    ds, ev1, ev2, ev3 = make_events()
    ds.merge_df(
        pandas.DataFrame({"code": [20, 21, 20],
                          "code2": [10, 10, 11],
                          "foo": ["a", "b", "c"]}),
        on={"code": "code2", "code2": "code"},
        subset="code == 10")
    assert dict(ev1) == {"code": 10, "code2": 20, "foo": "a"}
    assert dict(ev2) == {"code": 10, "code2": 21, "foo": "b"}
    assert dict(ev3) == {"code": 11, "code2": 20}