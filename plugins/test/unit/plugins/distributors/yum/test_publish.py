# -*- coding: utf-8 -*-
#
# Copyright © 2013 Red Hat, Inc.
#
# This software is licensed to you under the GNU General Public License as
# published by the Free Software Foundation; either version 2 of the License
# (GPLv2) or (at your option) any later version.
# There is NO WARRANTY for this software, express or implied, including the
# implied warranties of MERCHANTABILITY, NON-INFRINGEMENT, or FITNESS FOR A
# PARTICULAR PURPOSE.
# You should have received a copy of GPLv2 along with this software;
# if not, see http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt

import os
import shutil
import unittest
import tempfile
import sys
import traceback

import mock

from pulp.plugins.conduits.repo_publish import RepoPublishConduit
from pulp.plugins.config import PluginCallConfiguration
from pulp.plugins.model import Repository, Unit
from pulp.server.exceptions import InvalidValue

from pulp_rpm.common import constants
from pulp_rpm.common.ids import (
    TYPE_ID_PKG_GROUP, TYPE_ID_PKG_CATEGORY, TYPE_ID_DISTRO, TYPE_ID_DRPM, TYPE_ID_RPM,
    TYPE_ID_YUM_REPO_METADATA_FILE, YUM_DISTRIBUTOR_ID)
from pulp_rpm.plugins.distributors.yum import publish, reporting


DATA_DIR = os.path.join(os.path.dirname(__file__), '../../../../data/')


class BaseYumDistributorPublishTests(unittest.TestCase):

    def setUp(self):
        super(BaseYumDistributorPublishTests, self).setUp()
        self.published_dir = tempfile.mkdtemp()
        self.working_dir = tempfile.mkdtemp()

        self.publisher = None

    def tearDown(self):
        super(BaseYumDistributorPublishTests, self).tearDown()
        try:
            if os.path.exists(self.published_dir):
                shutil.rmtree(self.published_dir)
        except Exception:
            pass

        try:
            if os.path.exists(self.working_dir):
                shutil.rmtree(self.working_dir)
        except Exception:
            pass

        self.publisher = None

    def _init_publisher(self):

        repo = Repository('yum-distributor-publish-tests', working_dir=self.working_dir)

        conduit = RepoPublishConduit(repo.id, YUM_DISTRIBUTOR_ID)
        conduit.get_repo_scratchpad = mock.Mock(return_value={})

        config_defaults = {'http': True,
                           'https': True,
                           'relative_url': None,
                           'http_publish_dir': os.path.join(self.published_dir, 'http'),
                           'https_publish_dir': os.path.join(self.published_dir, 'https')}
        config = PluginCallConfiguration(None, None)
        config.default_config.update(config_defaults)

        self.publisher = publish.Publisher(repo, conduit, config)

        # mock out the repomd_file_context, so _publish_<step> can be called
        # outside of the publish() method
        self.publisher.repomd_file_context = mock.MagicMock()

    @staticmethod
    def _touch(path):

        parent = os.path.dirname(path)

        if not os.path.exists(parent):
            os.makedirs(parent)

        with open(path, 'w'):
            pass

    def _generate_rpm(self, name):

        unit_key = {'name': name,
                    'epoch': 0,
                    'version': 1,
                    'release': 0,
                    'arch': 'noarch',
                    'checksumtype': 'sha256',
                    'checksum': '1234657890'}

        unit_metadata = {'repodata': {'filelists': 'FILELISTS',
                                      'other': 'OTHER',
                                      'primary': 'PRIMARY'}}

        storage_path = os.path.join(self.working_dir, 'content', name)
        self._touch(storage_path)

        return Unit(TYPE_ID_RPM, unit_key, unit_metadata, storage_path)


class BaseYumDistributorPublishStepTests(BaseYumDistributorPublishTests):

    def setUp(self):
        super(BaseYumDistributorPublishStepTests, self).setUp()
        self._init_publisher()

    def tearDown(self):
        super(BaseYumDistributorPublishStepTests, self).tearDown()


class PublisherTests(BaseYumDistributorPublishTests):

    # -- cleanup testing -------------------------------------------------------

    def test_clear_directory(self):

        for file_name in ('one', 'two', 'three'):
            self._touch(os.path.join(self.working_dir, file_name))

        self.assertEqual(len(os.listdir(self.working_dir)), 3)

        publish.Publisher._clear_directory(self.working_dir)

        self.assertEqual(len(os.listdir(self.working_dir)), 0)

    # -- linking testing -------------------------------------------------------

    def test_create_symlink(self):
        source_path = os.path.join(self.working_dir, 'source')
        link_path = os.path.join(self.published_dir, 'link')

        self._touch(source_path)
        self.assertFalse(os.path.exists(link_path))

        publish.PublishStep._create_symlink(source_path, link_path)

        self.assertTrue(os.path.exists(link_path))
        self.assertTrue(os.path.islink(link_path))
        self.assertEqual(os.readlink(link_path), source_path)

    def test_create_symlink_no_source(self):
        source_path = os.path.join(self.working_dir, 'source')
        link_path = os.path.join(self.published_dir, 'link')

        self.assertRaises(RuntimeError, publish.PublishStep._create_symlink, source_path, link_path)

    def test_create_symlink_no_link_parent(self):
        source_path = os.path.join(self.working_dir, 'source')
        link_path = os.path.join(self.published_dir, 'foo/bar/baz/link')

        self._touch(source_path)
        self.assertFalse(os.path.exists(os.path.dirname(link_path)))

        publish.PublishStep._create_symlink(source_path, link_path)

        self.assertTrue(os.path.exists(link_path))

    def test_create_symlink_link_parent_bad_permissions(self):
        source_path = os.path.join(self.working_dir, 'source')
        link_path = os.path.join(self.published_dir, 'foo/bar/baz/link')

        self._touch(source_path)
        os.makedirs(os.path.dirname(link_path))
        os.chmod(os.path.dirname(link_path), 0000)

        self.assertRaises(OSError, publish.PublishStep._create_symlink, source_path, link_path)

        os.chmod(os.path.dirname(link_path), 0777)

    def test_create_symlink_link_exists(self):
        old_source_path = os.path.join(self.working_dir, 'old_source')
        new_source_path = os.path.join(self.working_dir, 'new_source')
        link_path = os.path.join(self.published_dir, 'link')

        self._touch(old_source_path)
        self._touch(new_source_path)

        os.symlink(old_source_path, link_path)

        self.assertEqual(os.readlink(link_path), old_source_path)

        publish.PublishStep._create_symlink(new_source_path, link_path)

        self.assertEqual(os.readlink(link_path), new_source_path)

    def test_create_symlink_link_exists_not_link(self):
        source_path = os.path.join(self.working_dir, 'source')
        link_path = os.path.join(self.published_dir, 'link')

        self._touch(source_path)
        self._touch(link_path)

        self.assertRaises(RuntimeError, publish.PublishStep._create_symlink, source_path, link_path)

    def test_symlink_content(self):
        self._init_publisher()
        unit_name = 'test.rpm'
        unit = self._generate_rpm(unit_name)
        step = publish.PublishStep(self.publisher, "foo", "bar")

        step._symlink_content(unit, self.published_dir)

        self.assertTrue(os.path.exists(os.path.join(self.published_dir, unit_name)),
                        str(os.listdir(self.published_dir)))
        self.assertTrue(os.path.islink(os.path.join(self.published_dir, unit_name)))

    # -- progress testing ------------------------------------------------------

    def test_init_step_progress(self):
        self._init_publisher()

        step = constants.PUBLISH_STEPS[0]
        publish_step = publish.PublishStep(self.publisher, step)
        publish_step._init_step_progress_report(step)

        self.assertEqual(self.publisher.progress_report[step], reporting.PROGRESS_SUB_REPORT)

    def test_init_step_progress_not_a_step(self):
        self._init_publisher()

        step = 'not_a_step'
        publish_step = publish.PublishStep(self.publisher, step)

        self.assertRaises(AssertionError, publish_step._init_step_progress_report, step)

    @mock.patch('pulp.plugins.conduits.repo_publish.RepoPublishConduit.set_progress')
    def test_report_progress(self, mock_set_progress):
        self._init_publisher()

        step = constants.PUBLISH_STEPS[1]
        publish_step = publish.PublishStep(self.publisher, step)

        updates = {constants.PROGRESS_STATE_KEY: constants.STATE_COMPLETE,
                   constants.PROGRESS_TOTAL_KEY: 1,
                   constants.PROGRESS_PROCESSED_KEY: 1,
                   constants.PROGRESS_SUCCESSES_KEY: 1}

        publish_step._report_progress(step, **updates)

        self.assertEqual(self.publisher.progress_report[step], updates)

        mock_set_progress.assert_called_once_with(self.publisher.progress_report)

    def test_record_failure(self):
        self._init_publisher()
        step = constants.PUBLISH_STEPS[2]
        publish_step = publish.PublishStep(self.publisher, step)

        publish_step._init_step_progress_report(step)

        error_msg = 'Too bad, so sad'

        try:
            raise Exception(error_msg)

        except Exception, e:
            publish_step._record_failure(step, e)

        self.assertEqual(self.publisher.progress_report[step][constants.PROGRESS_FAILURES_KEY], 1)
        self.assertEqual(self.publisher.progress_report[step][constants.PROGRESS_ERROR_DETAILS_KEY][0]['error'], error_msg)

    def test_build_final_report_success(self):
        self._init_publisher()

        for step in constants.PUBLISH_STEPS:
            publish_step = publish.PublishStep(self.publisher, step)
            publish_step._init_step_progress_report(step)
            self.publisher.progress_report[step][constants.PROGRESS_STATE_KEY] = constants.STATE_COMPLETE

        report = self.publisher._build_final_report()

        self.assertTrue(report.success_flag)

    def test_build_final_report_failure(self):
        self._init_publisher()

        for step in constants.PUBLISH_STEPS:
            publish_step = publish.PublishStep(self.publisher, step)
            publish_step._init_step_progress_report(step)
            self.publisher.progress_report[step][constants.PROGRESS_STATE_KEY] = constants.STATE_FAILED
            self.publisher.progress_report[step][constants.PROGRESS_ERROR_DETAILS_KEY].append('boo hoo')

        report = self.publisher._build_final_report()

        self.assertFalse(report.success_flag)

    # -- publish api testing ---------------------------------------------------

    def test_skip_list_with_list(self):
        self._init_publisher()
        mock_config = mock.Mock()
        mock_config.get.return_value = ['foo', 'bar']
        self.publisher.config = mock_config
        skip_list = self.publisher.skip_list
        self.assertEquals(2, len(skip_list))
        self.assertEquals(skip_list[0], 'foo')
        self.assertEquals(skip_list[1], 'bar')

    def test_skip_list_with_dict(self):
        self._init_publisher()
        mock_config = mock.Mock()
        mock_config.get.return_value = {'rpm': True, 'distro': False, 'errata': True}
        self.publisher.config = mock_config
        skip_list = self.publisher.skip_list
        self.assertEquals(2, len(skip_list))
        self.assertEquals(skip_list[0], 'rpm')
        self.assertEquals(skip_list[1], 'errata')

    @mock.patch('pulp.server.managers.factory.repo_distributor_manager')
    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.PublishCompsStep')
    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.Publisher._build_final_report')
    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.Publisher._clear_directory')
    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.PublishOverHttpsStep')
    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.PublishOverHttpStep')
    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.PublishMetadataStep')
    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.PublishErrataStep')
    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.PublishDrpmStep')
    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.PublishRpmStep')
    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.PublishDistributionStep')
    def test_publish(self, mock_publish_distribution, mock_publish_rpms, mock_publish_drpms,
                     mock_publish_errata, mock_publish_metadata, mock_publish_over_http, mock_publish_over_https,
                     mock_clear_directory, mock_build_final_report, mock_publish_comps,
                     mock_distributor_manager):

        self._init_publisher()
        self.publisher.repo.content_unit_counts = {}
        self.publisher.publish()

        mock_publish_distribution.assert_called_once()
        mock_publish_rpms.assert_called_once()
        mock_publish_drpms.assert_called_once()
        mock_publish_errata.assert_called_once()
        mock_publish_metadata.assert_called_once()
        mock_publish_over_http.assert_called_once()
        mock_publish_over_https.assert_called_once()
        mock_clear_directory.assert_called_once_with(self.publisher.repo.working_dir)
        mock_build_final_report.assert_called_once()
        mock_publish_comps.assert_called_once()

        self.assertTrue(os.path.exists(self.publisher.repo.working_dir))
        # repomd.xml should have been automatically created
        self.assertTrue(os.path.exists(os.path.join(self.publisher.repo.working_dir, 'repodata', 'repomd.xml')))

    def test_cancel(self):
        self._init_publisher()
        step = constants.PUBLISH_STEPS[0]
        publish_step = publish.PublishStep(self.publisher, step)
        publish_step._init_step_progress_report(step)

        self.publisher.cancel()

        self.assertTrue(self.publisher.canceled)
        self.assertEqual(self.publisher.progress_report[step][constants.PROGRESS_STATE_KEY], constants.STATE_CANCELLED)

        for s in constants.PUBLISH_STEPS[1:]:
            self.assertEqual(self.publisher.progress_report[s][constants.PROGRESS_STATE_KEY], constants.STATE_NOT_STARTED)


class PublishStepTests(BaseYumDistributorPublishStepTests):

    def test_publish_step_skip_units(self):
        self.publisher.config = PluginCallConfiguration(None, {'skip': [TYPE_ID_RPM]})
        step = publish.PublishStep(self.publisher, constants.PUBLISH_RPMS_STEP,
                                   TYPE_ID_RPM)
        step.process()

        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_RPMS_STEP]
                         [constants.PROGRESS_STATE_KEY],
                         constants.STATE_SKIPPED)

    def test_publish_step_no_units(self):
        self.publisher.repo.content_unit_counts = {TYPE_ID_RPM: 0}
        mock_method = mock.Mock()
        step = publish.PublishStep(self.publisher, constants.PUBLISH_RPMS_STEP,
                                   TYPE_ID_RPM)
        step.process_unit = mock_method
        step.process()

        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_RPMS_STEP]
                         [constants.PROGRESS_STATE_KEY],
                         constants.STATE_COMPLETE)
        self.assertFalse(mock_method.called)

    @mock.patch('pulp.plugins.conduits.repo_publish.RepoPublishConduit.get_units')
    def test_publish_step_single_unit(self, mock_get_units):
        self.publisher.repo.content_unit_counts = {TYPE_ID_RPM: 1}
        mock_method = mock.Mock()
        mock_get_units.return_value = ['mock_unit']
        step = publish.PublishStep(self.publisher, constants.PUBLISH_RPMS_STEP,
                                   TYPE_ID_RPM)
        step.process_unit = mock_method
        step.process()

        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_RPMS_STEP]
                         [constants.PROGRESS_STATE_KEY],
                         constants.STATE_COMPLETE)
        mock_method.assert_called_once_with('mock_unit')
        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_RPMS_STEP][
                         constants.PROGRESS_TOTAL_KEY], 1)
        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_RPMS_STEP][
                         constants.PROGRESS_PROCESSED_KEY], 1)
        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_RPMS_STEP][
                         constants.PROGRESS_FAILURES_KEY], 0)
        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_RPMS_STEP][
                         constants.PROGRESS_SUCCESSES_KEY], 1)

    @mock.patch('pulp.plugins.conduits.repo_publish.RepoPublishConduit.get_units')
    def test_publish_step_single_unit_exception(self, mock_get_units):
        self.publisher.repo.content_unit_counts = {TYPE_ID_RPM: 1}
        mock_method = mock.Mock(side_effect=Exception())
        mock_get_units.return_value = ['mock_unit']
        step = publish.PublishStep(self.publisher, constants.PUBLISH_RPMS_STEP,
                                   TYPE_ID_RPM)
        step.process_unit = mock_method

        self.assertRaises(Exception, step.process)

        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_RPMS_STEP]
                         [constants.PROGRESS_STATE_KEY],
                         constants.STATE_FAILED)
        mock_method.assert_called_once_with('mock_unit')
        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_RPMS_STEP][
                         constants.PROGRESS_TOTAL_KEY], 1)
        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_RPMS_STEP][
                         constants.PROGRESS_PROCESSED_KEY], 1)
        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_RPMS_STEP][
                         constants.PROGRESS_FAILURES_KEY], 1)
        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_RPMS_STEP][
                         constants.PROGRESS_SUCCESSES_KEY], 0)

    @mock.patch('pulp.plugins.conduits.repo_publish.RepoPublishConduit.get_units')
    def test_publish_step_failure_reported_on_metadata_finalized(self, mock_get_units):
        self.publisher.repo.content_unit_counts = {TYPE_ID_RPM: 1}
        mock_get_units.return_value = ['mock_unit']
        step = publish.PublishStep(self.publisher, constants.PUBLISH_RPMS_STEP,
                                   TYPE_ID_RPM)
        step.finalize_metadata = mock.Mock(side_effect=Exception())
        self.assertRaises(Exception, step.process)

        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_RPMS_STEP]
                         [constants.PROGRESS_STATE_KEY],
                         constants.STATE_FAILED)
        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_RPMS_STEP][
                         constants.PROGRESS_TOTAL_KEY], 1)
        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_RPMS_STEP][
                         constants.PROGRESS_PROCESSED_KEY], 1)
        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_RPMS_STEP][
                         constants.PROGRESS_FAILURES_KEY], 1)
        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_RPMS_STEP][
                         constants.PROGRESS_SUCCESSES_KEY], 1)

    # -- progress testing ------------------------------------------------------

    def test_init_step_progress(self):
        self._init_publisher()

        step = reporting.PUBLISH_STEPS[0]
        publish_step = publish.PublishStep(self.publisher, step)
        publish_step._init_step_progress_report(step)

        self.assertEqual(self.publisher.progress_report[step], reporting.PROGRESS_SUB_REPORT)

    def test_init_step_progress_not_a_step(self):
        self._init_publisher()

        step = 'not_a_step'
        publish_step = publish.PublishStep(self.publisher, step)

        self.assertRaises(AssertionError, publish_step._init_step_progress_report, step)

    @mock.patch('pulp.plugins.conduits.repo_publish.RepoPublishConduit.set_progress')
    def test_report_progress(self, mock_set_progress):
        self._init_publisher()

        step = reporting.PUBLISH_STEPS[1]
        publish_step = publish.PublishStep(self.publisher, step)

        updates = {reporting.STATE: reporting.PUBLISH_FINISHED_STATE,
                   reporting.TOTAL: 1,
                   reporting.PROCESSED: 1,
                   reporting.SUCCESSES: 1}

        publish_step._report_progress(step, **updates)

        self.assertEqual(self.publisher.progress_report[step], updates)

        mock_set_progress.assert_called_once_with(self.publisher.progress_report)

    def test_record_failure(self):
        self._init_publisher()
        step = reporting.PUBLISH_STEPS[2]
        publish_step = publish.PublishStep(self.publisher, step)

        publish_step._init_step_progress_report(step)

        error_msg = 'Too bad, so sad'

        try:
            raise Exception(error_msg)

        except Exception, e:
            tb = exc_traceback = sys.exc_info()[2]
            publish_step._record_failure(step, e, tb)

        self.assertEqual(self.publisher.progress_report[step][reporting.FAILURES], 1)
        # The Tracebck and error message should be separated into separate fields.
        details = traceback.format_tb(tb)
        details.extend([e.message])
        details = '\n'.join(details)
        self.assertEqual(self.publisher.progress_report[step][reporting.ERROR_DETAILS][0], details)

    # -- linking testing -------------------------------------------------------

    def test_create_symlink(self):
        source_path = os.path.join(self.working_dir, 'source')
        link_path = os.path.join(self.published_dir, 'link')

        self._touch(source_path)
        self.assertFalse(os.path.exists(link_path))

        publish.PublishStep._create_symlink(source_path, link_path)

        self.assertTrue(os.path.exists(link_path))
        self.assertTrue(os.path.islink(link_path))
        self.assertEqual(os.readlink(link_path), source_path)

    def test_create_symlink_no_source(self):
        source_path = os.path.join(self.working_dir, 'source')
        link_path = os.path.join(self.published_dir, 'link')

        self.assertRaises(RuntimeError, publish.PublishStep._create_symlink, source_path, link_path)

    def test_create_symlink_no_link_parent(self):
        source_path = os.path.join(self.working_dir, 'source')
        link_path = os.path.join(self.published_dir, 'foo/bar/baz/link')

        self._touch(source_path)
        self.assertFalse(os.path.exists(os.path.dirname(link_path)))

        publish.PublishStep._create_symlink(source_path, link_path)

        self.assertTrue(os.path.exists(link_path))

    def test_create_symlink_link_parent_bad_permissions(self):
        source_path = os.path.join(self.working_dir, 'source')
        link_path = os.path.join(self.published_dir, 'foo/bar/baz/link')

        self._touch(source_path)
        os.makedirs(os.path.dirname(link_path))
        os.chmod(os.path.dirname(link_path), 0000)

        self.assertRaises(OSError, publish.PublishStep._create_symlink, source_path, link_path)

        os.chmod(os.path.dirname(link_path), 0777)

    def test_create_symlink_link_exists(self):
        old_source_path = os.path.join(self.working_dir, 'old_source')
        new_source_path = os.path.join(self.working_dir, 'new_source')
        link_path = os.path.join(self.published_dir, 'link')

        self._touch(old_source_path)
        self._touch(new_source_path)

        os.symlink(old_source_path, link_path)

        self.assertEqual(os.readlink(link_path), old_source_path)

        publish.PublishStep._create_symlink(new_source_path, link_path)

        self.assertEqual(os.readlink(link_path), new_source_path)

    def test_create_symlink_link_exists_not_link(self):
        source_path = os.path.join(self.working_dir, 'source')
        link_path = os.path.join(self.published_dir, 'link')

        self._touch(source_path)
        self._touch(link_path)

        self.assertRaises(RuntimeError, publish.PublishStep._create_symlink, source_path, link_path)

    def test_symlink_content(self):
        self._init_publisher()
        unit_name = 'test.rpm'
        unit = self._generate_rpm(unit_name)
        step = publish.PublishStep(self.publisher, "foo", "bar")

        step._symlink_content(unit, self.published_dir)

        self.assertTrue(os.path.exists(os.path.join(self.published_dir, unit_name)),
                        str(os.listdir(self.published_dir)))
        self.assertTrue(os.path.islink(os.path.join(self.published_dir, unit_name)))


class PublishCompsStepTests(BaseYumDistributorPublishStepTests):

    def test_units_total(self):
        self._init_publisher()
        step = publish.PublishCompsStep(self.publisher)
        self.publisher.repo.content_unit_counts = {TYPE_ID_PKG_CATEGORY: 3, TYPE_ID_PKG_GROUP: 5}
        self.assertEquals(8, step._get_total())

    def test_units_generator(self):
        self._init_publisher()
        step = publish.PublishCompsStep(self.publisher)
        step.comps_context = mock.Mock()
        self.publisher.conduit.get_units = mock.Mock(side_effect=[['foo', 'bar'],
                                                                  ['baz', 'qux'],
                                                                  ['quux', 'waldo']])

        unit_list = [x.unit for x in step.get_unit_generator()]
        self.assertEquals(unit_list, ['foo', 'bar', 'baz', 'qux', 'quux', 'waldo'])

    def test_process_unit(self):
        # verify that the process unit calls the unit process method
        self._init_publisher()
        step = publish.PublishCompsStep(self.publisher)
        mock_unit = mock.Mock()
        step.process_unit(mock_unit)
        mock_unit.process.assert_called_once_with(mock_unit.unit)

    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.PackageXMLFileContext')
    def test_initialize_metadata(self, mock_context):
        self._init_publisher()
        step = publish.PublishCompsStep(self.publisher)
        step.initialize_metadata()
        mock_context.return_value.initialize.assert_called_once_with()

    def test_finalize_metadata(self):
        self._init_publisher()
        step = publish.PublishCompsStep(self.publisher)
        step.comps_context = mock.Mock()
        step.finalize_metadata()
        step.comps_context.finalize.assert_called_once_with()
        self.publisher.repomd_file_context.\
            add_metadata_file_metadata.assert_called_once_with('group', mock.ANY)


class PublishDrpmStepTests(BaseYumDistributorPublishStepTests):

    def _generate_drpm(self, name):

        unit_key = {'epoch': '0',
                    'version': '1',
                    'release': '1',
                    'filename': name,
                    'checksumtype': 'sha256',
                    'checksum': '1234567890'}

        unit_metadata = {'new_package': name,
                         'arch': 'noarch',
                         'oldepoch': '0',
                         'oldversion': '1',
                         'oldrelease': '0',
                         'sequence': '0987654321',
                         'size': 5}

        storage_path = os.path.join(self.working_dir, 'content', name)
        self._touch(storage_path)

        return Unit(TYPE_ID_DRPM, unit_key, unit_metadata, storage_path)


    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.PublishStep._symlink_content')
    def test_process_unit(self, mock_symlink):
        step = publish.PublishDrpmStep(self.publisher)
        test_unit = 'foo'

        step.context = mock.Mock()
        step.process_unit(test_unit)

        mock_symlink.assert_called_once_with(test_unit, os.path.join(self.working_dir, 'drpms'))
        step.context.add_unit_metadata.assert_called_once_with(test_unit)

    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.PublishStep._symlink_content')
    def test_process_unit_links_packages_dir(self, mock_symlink):
        step = publish.PublishDrpmStep(self.publisher)
        test_unit = 'foo'
        self.publisher.package_dir = 'bar'
        step.context = mock.Mock()
        step.process_unit(test_unit)

        mock_symlink.assert_any_call(test_unit, os.path.join(self.working_dir, 'drpms'))

    @mock.patch('pulp.plugins.conduits.repo_publish.RepoPublishConduit.get_units')
    def test_publish_drpms(self, mock_get_units):
        self.publisher.repo.content_unit_counts = {TYPE_ID_DRPM: 2}

        units = [self._generate_drpm(u) for u in ('A', 'B')]
        mock_get_units.return_value = units

        publish.PublishDrpmStep(self.publisher).process()

        for u in units:
            path = os.path.join(self.working_dir, 'drpms', u.unit_key['filename'])
            self.assertTrue(os.path.exists(path))
            self.assertTrue(os.path.islink(path))

        self.assertTrue(os.path.exists(
            os.path.join(self.working_dir, 'repodata/prestodelta.xml.gz')))


class PublishDistributionStepTests(BaseYumDistributorPublishStepTests):

    def _generate_distribution_unit(self, name, metadata = {}):
        storage_path = os.path.join(self.working_dir, 'content', name)
        if not os.path.exists(storage_path):
            os.makedirs(storage_path)

        unit_key = {"id": name}
        unit_metadata = {"files": [
            {
              "downloadurl": "http://download-01.eng.brq.redhat.com/pub/rhel/released/RHEL-6/6.4/Server/x86_64/os/images/boot.iso",
              "item_type": "distribution",
              "savepath": "/var/lib/pulp/working/repos/distro/importers/yum_importer/tmpGn5a2b/tmpE7TPuQ/images/boot.iso",
              "checksumtype": "sha256",
              "relativepath": "images/boot.iso",
              "checksum": "929669e1203117f2b6a0d94f963af11db2eafe84f05c42c7e582d285430dc7a4",
              "pkgpath": "/var/lib/pulp/content/distribution/ks-Red Hat Enterprise Linux-Server-6.4-x86_64/images",
              "filename": "boot.iso"
            }
        ]}
        unit_metadata.update(metadata)
        self._touch(os.path.join(storage_path, 'images', 'boot.iso'))

        return Unit(TYPE_ID_DISTRO, unit_key, unit_metadata, storage_path)

    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.PublishDistributionStep._publish_distribution_packages_link')
    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.PublishDistributionStep._publish_distribution_treeinfo')
    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.PublishDistributionStep._publish_distribution_files')
    @mock.patch('pulp.plugins.conduits.repo_publish.RepoPublishConduit.get_units')
    def test_publish_distribution(self, mock_get_units, mock_files, mock_treeinfo, mock_packages):
        self.publisher.repo.content_unit_counts = {TYPE_ID_DISTRO: 1}
        units = [self._generate_distribution_unit(u) for u in ('one', )]
        mock_get_units.return_value = units

        publish.PublishDistributionStep(self.publisher).process()

        mock_files.assert_called_once_with(units[0])
        mock_treeinfo.assert_called_once_with(units[0])
        mock_packages.assert_called_once_with(units[0])
        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_DISTRIBUTION_STEP][constants.PROGRESS_STATE_KEY], constants.STATE_COMPLETE)

    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.PublishStep._init_step_progress_report')
    def test_publish_distribution_canceled(self, mock_progress_report):
        self.publisher.canceled = True
        publish.PublishDistributionStep(self.publisher).process()
        self.assertFalse(mock_progress_report.called)


    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.PublishStep._record_failure')
    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.PublishDistributionStep._publish_distribution_treeinfo')
    @mock.patch('pulp.plugins.conduits.repo_publish.RepoPublishConduit.get_units')
    def test_publish_distribution_error(self, mock_get_units, mock_treeinfo, mock_record_failure):
        self.publisher.repo.content_unit_counts = {TYPE_ID_DISTRO: 1}
        units = [self._generate_distribution_unit(u) for u in ('one', )]
        mock_get_units.return_value = units
        error = Exception('Test Error')
        mock_treeinfo.side_effect = error
        step = publish.PublishDistributionStep(self.publisher)
        self.assertRaises(Exception, step.process)

        mock_record_failure.assert_called_once_with(constants.PUBLISH_DISTRIBUTION_STEP, error)

    def test_publish_distribution_multiple_distribution(self):
        step = publish.PublishDistributionStep(self.publisher)
        step._get_total = mock.Mock(return_value=2)
        self.assertRaises(Exception, step.initialize_metadata)

    def test_publish_distribution_treeinfo_does_nothing_if_no_treeinfo_file(self):
        unit = self._generate_distribution_unit('one')
        step = publish.PublishDistributionStep(self.publisher)
        step._init_step_progress_report(constants.PUBLISH_DISTRIBUTION_STEP)
        step._publish_distribution_treeinfo(unit)
        self.assertEquals(
            self.publisher.progress_report[constants.PUBLISH_DISTRIBUTION_STEP][constants.PROGRESS_PROCESSED_KEY], 0)

    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.PublishStep._create_symlink')
    def _perform_treeinfo_success_test(self, treeinfo_name, mock_symlink):
        unit = self._generate_distribution_unit('one')
        file_name = os.path.join(unit.storage_path, treeinfo_name)
        open(file_name, 'a').close()
        target_directory = os.path.join(self.publisher.repo.working_dir, treeinfo_name)
        step = publish.PublishDistributionStep(self.publisher)
        step._init_step_progress_report(constants.PUBLISH_DISTRIBUTION_STEP)
        step._publish_distribution_treeinfo(unit)

        mock_symlink.assert_called_once_with(file_name, target_directory)
        self.assertEquals(
            self.publisher.progress_report[constants.PUBLISH_DISTRIBUTION_STEP][constants.PROGRESS_PROCESSED_KEY], 1)
        self.assertEquals(
            self.publisher.progress_report[constants.PUBLISH_DISTRIBUTION_STEP][constants.PROGRESS_SUCCESSES_KEY], 1)

    def test_publish_distribution_treeinfo_finds_treeinfo(self):
        self._perform_treeinfo_success_test('treeinfo')

    def test_publish_distribution_treeinfo_finds_dot_treeinfo(self):
        self._perform_treeinfo_success_test('.treeinfo')

    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.PublishStep._create_symlink')
    def test_publish_distribution_treeinfo_error(self, mock_symlink):
        unit = self._generate_distribution_unit('one')
        file_name = os.path.join(unit.storage_path, 'treeinfo')
        open(file_name, 'a').close()
        target_directory = os.path.join(self.publisher.repo.working_dir, 'treeinfo')
        mock_symlink.side_effect = Exception("Test Error")
        step = publish.PublishDistributionStep(self.publisher)
        step._init_step_progress_report(constants.PUBLISH_DISTRIBUTION_STEP)

        self.assertRaises(Exception, step._publish_distribution_treeinfo, unit)

        mock_symlink.assert_called_once_with(file_name, target_directory)
        self.assertEquals(
            self.publisher.progress_report[constants.PUBLISH_DISTRIBUTION_STEP][constants.PROGRESS_PROCESSED_KEY], 0)
        self.assertEquals(
            self.publisher.progress_report[constants.PUBLISH_DISTRIBUTION_STEP][constants.PROGRESS_SUCCESSES_KEY], 0)

    def test_publish_distribution_files(self):
        unit = self._generate_distribution_unit('one')
        step = publish.PublishDistributionStep(self.publisher)
        step._init_step_progress_report(constants.PUBLISH_DISTRIBUTION_STEP)
        step._publish_distribution_files(unit)

        content_file = os.path.join(unit.storage_path, 'images', 'boot.iso')
        created_link = os.path.join(self.publisher.repo.working_dir, "images", 'boot.iso')
        self.assertTrue(os.path.islink(created_link))
        self.assertEquals(os.path.realpath(created_link), os.path.realpath(content_file))

    def test_publish_distribution_files_skips_repomd(self):
        unit = self._generate_distribution_unit('one')
        unit.metadata['files'][0]['relativepath'] = 'repodata/repomd.xml'
        step = publish.PublishDistributionStep(self.publisher)
        step._init_step_progress_report(reporting.PUBLISH_DISTRIBUTION_STEP)
        step._publish_distribution_files(unit)

        created_link = os.path.join(self.publisher.repo.working_dir, "repodata", 'repomd.xml')
        self.assertFalse(os.path.exists(created_link))

    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.PublishStep._create_symlink')
    def test_publish_distribution_files_error(self, mock_symlink):
        unit = self._generate_distribution_unit('one')
        mock_symlink.side_effect = Exception('Test Error')
        step = publish.PublishDistributionStep(self.publisher)

        self.assertRaises(Exception, step._publish_distribution_files, unit)

    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.PublishStep._create_symlink')
    def test_publish_distribution_files_no_files(self, mock_symlink):
        unit = self._generate_distribution_unit('one')
        unit.metadata.pop('files', None)
        publish.PublishDistributionStep(self.publisher)._publish_distribution_files(unit)
        #This would throw an exception if it didn't work properly

    def test_publish_distribution_packages_link(self):
        unit = self._generate_distribution_unit('one')
        step = publish.PublishDistributionStep(self.publisher)
        step._publish_distribution_packages_link(unit)

        created_link = os.path.join(self.publisher.repo.working_dir, 'Packages')
        self.assertTrue(os.path.islink(created_link))
        self.assertEquals(os.path.realpath(created_link),
                          os.path.realpath(self.publisher.repo.working_dir))

    def test_publish_distribution_packages_link_with_packagedir(self):
        unit = self._generate_distribution_unit('one', {'packagedir': 'Server'})
        step = publish.PublishDistributionStep(self.publisher)
        step._publish_distribution_packages_link(unit)
        self.assertEquals('Server', self.publisher.package_dir)

    def test_publish_distribution_packages_link_with_invalid_packagedir(self):
        self._init_publisher()
        step = publish.PublishDistributionStep(self.publisher)
        unit = self._generate_distribution_unit('one', {'packagedir': 'Server/../../foo'})
        self.assertRaises(InvalidValue, step._publish_distribution_packages_link, unit)

    def test_publish_distribution_packages_link_with_packagedir_equals_Packages(self):
        unit = self._generate_distribution_unit('one', {'packagedir': 'Packages'})
        step = publish.PublishDistributionStep(self.publisher)
        step._publish_distribution_packages_link(unit)
        packages_dir = os.path.join(self.publisher.repo.working_dir, 'Packages')
        self.assertEquals('Packages', self.publisher.package_dir)
        self.assertFalse(os.path.isdir(packages_dir))

    def test_publish_distribution_packages_link_with_packagedir_delete_existing_Packages(self):
        packages_dir = os.path.join(self.publisher.repo.working_dir, 'Packages')
        publish.PublishStep._create_symlink("./", packages_dir)
        unit = self._generate_distribution_unit('one', {'packagedir': 'Packages'})
        step = publish.PublishDistributionStep(self.publisher)
        step._publish_distribution_packages_link(unit)
        packages_dir = os.path.join(self.publisher.repo.working_dir, 'Packages')
        self.assertFalse(os.path.isdir(packages_dir))

    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.PublishStep._create_symlink')
    def test_publish_distribution_packages_link_error(self, mock_symlink):
        self._init_publisher()
        mock_symlink.side_effect = Exception("Test Error")
        step = publish.PublishDistributionStep(self.publisher)
        self.assertRaises(Exception, step._publish_distribution_packages_link)


class PublishRpmStepTests(BaseYumDistributorPublishStepTests):

    @mock.patch('pulp.plugins.conduits.repo_publish.RepoPublishConduit.get_units')
    def test_publish_rpms(self, mock_get_units):
        self.publisher.repo.content_unit_counts = {TYPE_ID_RPM: 3}

        units = [self._generate_rpm(u) for u in ('one', 'two', 'tree')]
        mock_get_units.return_value = units

        publish.PublishRpmStep(self.publisher).process()

        for u in units:
            path = os.path.join(self.working_dir, u.unit_key['name'])
            self.assertTrue(os.path.exists(path))
            self.assertTrue(os.path.islink(path))

        self.assertTrue(os.path.exists(os.path.join(self.working_dir, 'repodata/filelists.xml.gz')))
        self.assertTrue(os.path.exists(os.path.join(self.working_dir, 'repodata/other.xml.gz')))
        self.assertTrue(os.path.exists(os.path.join(self.working_dir, 'repodata/primary.xml.gz')))

    def test_process_unit_links_package_dir(self):
        unit = self._generate_rpm('one')
        package_dir = os.path.join(self.working_dir, 'packages')
        self.publisher.package_dir = package_dir
        step = publish.PublishRpmStep(self.publisher)
        step.initialize_metadata()
        step.process_unit(unit)

        unit_path = os.path.join(self.publisher.package_dir, unit.unit_key['name'])
        self.assertTrue(os.path.exists(unit_path))

class PublishErrataStepTests(BaseYumDistributorPublishStepTests):

    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.UpdateinfoXMLFileContext')
    def test_initialize_metadata(self, mock_context):
        self._init_publisher()
        step = publish.PublishErrataStep(self.publisher)
        step.initialize_metadata()
        mock_context.return_value.initialize.assert_called_once_with()
        self.assertEquals(step.process_unit, step.context.add_unit_metadata)

    def test_finalize_metadata(self):
        self._init_publisher()
        step = publish.PublishErrataStep(self.publisher)
        step.context = mock.Mock()
        step.finalize_metadata()
        step.context.finalize.assert_called_once_with()
        self.publisher.repomd_file_context.\
            add_metadata_file_metadata.assert_called_once_with('updateinfo', mock.ANY)


class PublishMetadataStepTests(BaseYumDistributorPublishStepTests):

    def _generate_metadata_file_unit(self, data_type, repo_id):

        unit_key = {'data_type' : data_type,
                    'repo_id' : repo_id}

        unit_metadata = {}

        storage_path = os.path.join(self.working_dir, 'content', 'metadata_files', data_type)
        self._touch(storage_path)

        return Unit(TYPE_ID_YUM_REPO_METADATA_FILE, unit_key, unit_metadata, storage_path)


    @mock.patch('pulp.plugins.conduits.repo_publish.RepoPublishConduit.get_units')
    def test_publish_metadata(self, mock_get_units):
        # Setup
        units = [self._generate_metadata_file_unit(dt, 'test-repo') for dt in ('A', 'B')]
        mock_get_units.return_value = units
        self.publisher.repo.content_unit_counts = {TYPE_ID_YUM_REPO_METADATA_FILE : len(units)}

        # Test
        publish.PublishMetadataStep(self.publisher).process()

        # Verify
        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_METADATA_STEP][constants.PROGRESS_STATE_KEY], constants.STATE_COMPLETE)
        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_METADATA_STEP][constants.PROGRESS_TOTAL_KEY], len(units))
        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_METADATA_STEP][constants.PROGRESS_FAILURES_KEY], 0)
        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_METADATA_STEP][constants.PROGRESS_SUCCESSES_KEY], len(units))

        for u in units:
            data_type = u.unit_key['data_type']
            path = os.path.join(self.working_dir, publish.REPO_DATA_DIR_NAME, data_type)
            self.assertTrue(os.path.exists(path))
            self.assertTrue(os.path.islink(path))
            self.assertTrue(os.path.exists(os.path.join(self.working_dir, 'repodata/%s' % data_type)))

    @mock.patch('pulp.plugins.conduits.repo_publish.RepoPublishConduit.get_units')
    def test_publish_metadata_failed(self, mock_get_units):
        # Setup
        units = [self._generate_metadata_file_unit(dt, 'test-repo') for dt in ('A', 'B')]
        mock_get_units.return_value = units
        self.publisher.repo.content_unit_counts = {TYPE_ID_YUM_REPO_METADATA_FILE : len(units)}

        mock_error_raiser = mock.MagicMock()
        mock_error_raiser.side_effect = Exception('foo')
        self.publisher.repomd_file_context.add_metadata_file_metadata = mock_error_raiser

        step = publish.PublishMetadataStep(self.publisher)
        step._get_total = mock.Mock(return_value=2)

        # Test
        self.assertRaises(Exception, step.process)

        # Verify
        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_METADATA_STEP][constants.PROGRESS_STATE_KEY], constants.STATE_FAILED)
        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_METADATA_STEP][constants.PROGRESS_TOTAL_KEY], len(units))
        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_METADATA_STEP][constants.PROGRESS_FAILURES_KEY], 1)
        self.assertEqual(self.publisher.progress_report[constants.PUBLISH_METADATA_STEP][constants.PROGRESS_SUCCESSES_KEY], 0)

    def test_publish_metadata_canceled(self):
        # Setup
        self.publisher.canceled = True
        mock_report_progress = mock.MagicMock()
        self.publisher._report_progress = mock_report_progress

        # Test
        publish.PublishMetadataStep(self.publisher).process()

        # Verify
        self.assertEqual(0, mock_report_progress.call_count)

    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.PublishStep._report_progress')
    def test_publish_metadata_skipped(self, mock_report_progress):
        # Setup
        self.publisher.config.repo_plugin_config['skip'] = [TYPE_ID_YUM_REPO_METADATA_FILE]

        # Test
        publish.PublishMetadataStep(self.publisher).process()

        # Verify
        mock_report_progress.assert_called_once_with(constants.PUBLISH_METADATA_STEP,
                                                     state=constants.STATE_SKIPPED)

    @mock.patch('pulp_rpm.plugins.distributors.yum.publish.PublishStep._report_progress')
    def test_publish_metadata_zero_count(self, mock_report_progress):
        # Test
        publish.PublishMetadataStep(self.publisher).process()

        # Verify
        mock_report_progress.assert_called_once_with(constants.PUBLISH_METADATA_STEP,
                                                     state=constants.STATE_COMPLETE,
                                                     total=0)


class PublishOverHttpTests(BaseYumDistributorPublishStepTests):

    def test_publish_http(self):
        units = [self._generate_rpm(u) for u in ('one', 'two', 'three')]

        publish.PublishOverHttpStep(self.publisher).process()
        for u in units:
            path = os.path.join(self.published_dir, 'http', self.publisher.repo.id, 'content', u.unit_key['name'])
            self.assertTrue(os.path.exists(path))

        listing_path = os.path.join(self.published_dir, 'http', 'listing')
        self.assertTrue(os.path.exists(listing_path))

        listing_content = open(listing_path, 'r').read()
        self.assertEqual(listing_content, self.publisher.repo.id)

    def test_publish_http_remove_existing_dir(self):
        units = [self._generate_rpm(u) for u in ('one', 'two', 'three')]

        # Make the existing directory and put something in it
        repo_directory = os.path.join(self.published_dir, 'http', self.publisher.repo.id)
        os.makedirs(repo_directory)
        file_path = os.path.join(repo_directory, 'foo')
        open(file_path, 'a').close()

        publish.PublishOverHttpStep(self.publisher).process()
        for u in units:
            path = os.path.join(self.published_dir, 'http', self.publisher.repo.id, 'content', u.unit_key['name'])
            self.assertTrue(os.path.exists(path))

        listing_path = os.path.join(self.published_dir, 'http', 'listing')
        self.assertTrue(os.path.exists(listing_path))

        listing_content = open(listing_path, 'r').read()
        self.assertEqual(listing_content, self.publisher.repo.id)

        # test that the original file has been removed
        self.assertFalse(os.path.exists(file_path))


class PublishOverHttpsStepTests(BaseYumDistributorPublishStepTests):

    def test_publish_https(self):
        units = [self._generate_rpm(u) for u in ('one', 'two', 'three')]

        publish.PublishOverHttpsStep(self.publisher).process()

        for u in units:
            path = os.path.join(self.published_dir, 'https', self.publisher.repo.id, 'content', u.unit_key['name'])
            self.assertTrue(os.path.exists(path))

        listing_path= os.path.join(self.published_dir, 'https', 'listing')
        self.assertTrue(os.path.exists(listing_path))

        listing_content = open(listing_path, 'r').read()
        self.assertEqual(listing_content, self.publisher.repo.id)