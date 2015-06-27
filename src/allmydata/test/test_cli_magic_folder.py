import os.path
import urllib
import re
import json

from twisted.trial import unittest

from allmydata.util import fileutil
from allmydata.scripts.common import get_aliases
from allmydata.scripts import cli, runner
from allmydata.test.no_network import GridTestMixin
from allmydata.util.encodingutil import quote_output, get_io_encoding
from .test_cli import CLITestMixin
from allmydata.scripts import magic_folder_cli
from allmydata.util.fileutil import abspath_expanduser_unicode


class MagicFolderCLITestMixin(CLITestMixin, GridTestMixin):

    def create_magic_folder(self, client_num):
        d = self.do_cli_n(client_num, "magic-folder", "create", "magic")
        def _done((rc,stdout,stderr)):
            self.failUnless(rc == 0)
            self.failUnless("Alias 'magic' created" in stdout)
            self.failIf(stderr)
            aliases = get_aliases(self.get_clientdir(i=client_num))
            self.failUnless("magic" in aliases)
            self.failUnless(aliases["magic"].startswith("URI:DIR2:"))
        d.addCallback(_done)
        return d

    def invite(self, client_num, nickname):
        d = self.do_cli_n(client_num, "magic-folder", "invite", u"magic", nickname)
        def _done((rc,stdout,stderr)):
            self.failUnless(rc == 0)
            return (rc,stdout,stderr)
        d.addCallback(_done)
        return d

    def join(self, client_num, local_dir, invite_result):
        invite_code = result[1].strip()
        magic_readonly_cap, dmd_write_cap = invite_code.split(magic_folder_cli.INVITE_SEPERATOR)
        d = self.do_cli_n(client_num, "magic-folder", "join", invite_code, local_dir)
        def _done((rc,stdout,stderr)):
            self.failUnless(rc == 0)
            return (rc,stdout,stderr)
        d.addCallback(_done)
        return d

    def diminish_readonly(self, write_cap):
        d = self.do_cli("ls", "--json", write_cap)
        def get_readonly_cap((rc,stdout,stderr)):
            self.failUnless(rc == 0)
            readonly_cap = json.loads(stdout)[1][u"ro_uri"]
            return readonly_cap
        d.addCallback(get_readonly_cap)
        return d

    def check_joined_config(self, client_num, upload_dircap):
        """Tests that our collective directory has the readonly cap of
        our upload directory.
        """
        collective_readonly_cap = fileutil.read(os.path.join(self.get_clientdir(i=client_num), "private/collective_dircap"))
        d = self.do_cli_n(client_num, "ls", "--json", collective_readonly_cap)
        def _done((rc,stdout,stderr)):
            self.failUnless(rc == 0)
            return (rc,stdout,stderr)
        d.addCallback(_done)
        def test_joined_magic_folder((rc,stdout,stderr)):
            d2 = self.diminish_readonly(upload_dircap)
            def fail_unless_dmd_readonly_exists(readonly_cap):
                s = re.search(readonly_cap, stdout)
                self.failUnless(s is not None)
            d2.addCallback(fail_unless_dmd_readonly_exists)
            return d2
        d.addCallback(test_joined_magic_folder)
        return d

    def get_caps_from_files(self, client_num):
        collective_dircap = fileutil.read(os.path.join(self.get_clientdir(i=client_num), "private/collective_dircap"))
        upload_dircap = fileutil.read(os.path.join(self.get_clientdir(i=client_num), "private/magic_folder_dircap"))
        self.failIf(collective_dircap is None or upload_dircap is None)
        return collective_dircap, upload_dircap

    def check_config(self, client_num, local_dir):
        client_config = fileutil.read(os.path.join(self.get_clientdir(i=client_num), "tahoe.cfg"))
        # XXX utf-8?
        local_dir = local_dir.encode('utf-8')
        ret = re.search("\[magic_folder\]\nenabled = True\nlocal.directory = %s" % (local_dir,), client_config)
        self.failIf(ret is None)

    def create_invite_join_magic_folder(self, nickname, local_dir):
        d = self.do_cli("magic-folder", "create", u"magic", nickname, local_dir)
        def _done((rc,stdout,stderr)):
            self.failUnless(rc == 0)
            return (rc,stdout,stderr)
        d.addCallback(_done)
        d.addCallback(self.get_caps_from_files)
        d.addCallback(self.check_joined_config)
        d.addCallback(self.check_config)
        return d

    def cleanup(self, res):
        d = defer.succeed(None)
        if self.magicfolder is not None:
            d.addCallback(lambda ign: self.magicfolder.finish(for_tests=True))
        d.addCallback(lambda ign: res)
        return d

    def init_magicfolder(self, client_num, upload_dircap, collective_dircap, local_magic_dir):
        dbfile = abspath_expanduser_unicode(u"magicfolderdb.sqlite", base=self.get_clientdir(i=client_num))
        self.magicfolder = MagicFolder(self.get_client(client_num), upload_dircap, collective_dircap, local_magic_dir,
                                       dbfile, inotify=self.inotify, pending_delay=0.2)
        self.magicfolder.setServiceParent(self.get_client(client_num))
        self.magicfolder.upload_ready()

    def setup_alice_and_bob(self):
        self.set_up_grid(num_clients=2)
        alice_dir = abspath_expanduser_unicode(u"Alice", base=self.basedir)
        self.mkdir_nonascii(alice_dir)
        alice_magic_dir = abspath_expanduser_unicode(u"Alice-magic", base=self.basedir)
        self.mkdir_nonascii(alice_magic_dir)
        bob_dir = abspath_expanduser_unicode(u"Bob", base=self.basedir)
        self.mkdir_nonascii(bob_dir)
        bob_magic_dir = abspath_expanduser_unicode(u"Bob-magic", base=self.basedir)
        self.mkdir_nonascii(bob_magic_dir)

        d = self.create_magic_folder(0)
        d.addCallback(lambda x: self.invite_n(0, x))
        d.addCallback(lambda x: self.join(0, alice_magic_dir, x))
        def get_alice_caps(x):
            alice_collective_dircap, alice_upload_dircap = self.get_caps_from_files(0)
        d.addCallback(get_alice_caps)
        d.addCallback(lambda x: self.check_joined_config(0, alice_upload_dircap))
        d.addCallback(lambda x: self.check_config(0, alice_magic_dir))
        d.addCallback(lambda x: self.init_magicfolder(0, alice_upload_dircap, alice_collective_dircap, alice_magic_dir))

        d.addCallback(lambda x: self.invite_n(0, u"Bob"))
        d.addCallback(lambda x: self.join(1, bob_magic_dir, x))
        def get_bob_caps(x):
            bob_collective_dircap, bob_upload_dircap = self.get_caps_from_files(1)
        d.addCallback(get_bob_caps)
        d.addCallback(lambda x: self.check_joined_config(1, bob_upload_dircap))
        d.addCallback(lambda x: self.check_config(1, bob_magic_dir))
        d.addCallback(lambda x: self.init_magicfolder(1, bob_upload_dircap, bob_collective_dircap, bob_magic_dir))

        return d

class CreateMagicFolder(MagicFolderCLITestMixin, unittest.TestCase):

    def test_create_and_then_invite_join(self):
        self.basedir = "cli/MagicFolder/create-and-then-invite-join"
        self.set_up_grid()
        self.local_dir = os.path.join(self.basedir, "magic")

        d = self.create_magic_folder(0)
        d.addCallback(self._invite)
        d.addCallback(self._join)
        d.addCallback(self.get_caps_from_files)
        d.addCallback(self.check_joined_config)
        d.addCallback(self.check_config)
        return d

    def test_create_invite_join(self):
        self.basedir = "cli/MagicFolder/create-invite-join"
        self.set_up_grid()
        self.local_dir = os.path.join(self.basedir, "magic")
        d = self.do_cli("magic-folder", "create", u"magic", u"Alice", self.local_dir)
        def _done((rc,stdout,stderr)):
            self.failUnless(rc == 0)
            return (rc,stdout,stderr)
        d.addCallback(_done)
        d.addCallback(self.get_caps_from_files)
        d.addCallback(self.check_joined_config)
        d.addCallback(self.check_config)
        return d
