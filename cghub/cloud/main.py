from collections import OrderedDict
import logging
import os
import sys
from operator import itemgetter

import boto
from cghub.cloud.devenv.genetorrent_jenkins_slaves import Centos6GenetorrentJenkinsSlave, Centos5GenetorrentJenkinsSlave, UbuntuPreciseGenetorrentJenkinsSlave, UbuntuLucidGenetorrentJenkinsSlave, UbuntuRaringGenetorrentJenkinsSlave, UbuntuOneiricGenetorrentJenkinsSlave, Fedora19GenetorrentJenkinsSlave, Fedora18GenetorrentJenkinsSlave, Fedora17GenetorrentJenkinsSlave
from cghub.cloud.generic_boxes import GenericCentos6Box, GenericCentos5Box, GenericUbuntuMaverickBox, GenericUbuntuLucidBox, GenericUbuntuOneiricBox, GenericUbuntuNattyBox, GenericUbuntuQuantalBox, GenericUbuntuPreciseBox, GenericUbuntuRaringBox, GenericUbuntuSaucyBox, GenericFedora17Box, GenericFedora18Box, GenericFedora19Box

from devenv.jenkins_master import JenkinsMaster

from util import Command, Application
from environment import Environment


DEBUG_LOG_FILE_NAME = 'cgcloud.log'

# After adding a new box class, add its name to the source list in the generator expression below
BOXES = OrderedDict( ( cls.role( ), cls) for cls in [
    GenericCentos6Box,
    GenericCentos5Box,
    GenericUbuntuLucidBox,
    GenericUbuntuMaverickBox,
    GenericUbuntuNattyBox,
    GenericUbuntuOneiricBox,
    GenericUbuntuPreciseBox,
    GenericUbuntuQuantalBox,
    GenericUbuntuRaringBox,
    GenericUbuntuSaucyBox,
    GenericFedora17Box,
    GenericFedora18Box,
    GenericFedora19Box,
    JenkinsMaster,
    UbuntuLucidGenetorrentJenkinsSlave,
    UbuntuOneiricGenetorrentJenkinsSlave,
    UbuntuPreciseGenetorrentJenkinsSlave,
    UbuntuRaringGenetorrentJenkinsSlave,
    Centos5GenetorrentJenkinsSlave,
    Centos6GenetorrentJenkinsSlave,
    Fedora17GenetorrentJenkinsSlave,
    Fedora18GenetorrentJenkinsSlave,
    Fedora19GenetorrentJenkinsSlave,
] )


def main():
    app = Cgcloud( )
    for c in [
        ListRolesCommand,
        CreateCommand,
        StartCommand,
        StopCommand,
        RebootCommand,
        TerminateCommand,
        CreateImageCommand,
        ShowCommand,
        SshCommand,
        ListCommand,
        GetKeysCommand,
        ListImages,
        UploadKeyCommand,
    ]: app.add( c )
    app.run( )


class Cgcloud( Application ):
    def __init__(self):
        super( Cgcloud, self ).__init__( )
        self.option( '--debug',
                     default=False, action='store_true',
                     help='Write debug log to %s in current directory.' % DEBUG_LOG_FILE_NAME )

    def prepare(self, options):
        if options.debug:
            logging.basicConfig( filename=DEBUG_LOG_FILE_NAME, level=logging.DEBUG )


class EnvironmentCommand( Command ):
    def run_in_env(self, options, env):
        """
        Run this command in the given environment.

        :type env: Environment
        """
        raise NotImplementedError( )

    def __init__(self, application, **kwargs):
        defaults = Environment( )
        super( EnvironmentCommand, self ).__init__( application, **kwargs )
        self.option( '--zone', '-z', metavar='AVAILABILITY_ZONE',
                     default=os.environ.get( 'CGCLOUD_ZONE', defaults.availability_zone ),
                     dest='availability_zone',
                     help='The name of the EC2 availability zone to place EC2 resources into, '
                          'e.g. us-east-1a, us-west-1b or us-west-2c etc. This argument implies '
                          'the AWS region to run in. The value of the environment variable '
                          'CGCLOUD_ZONE, if that variable is present, overrides the default.' )

        self.option( '--namespace', '-n', metavar='PREFIX',
                     default=os.environ.get( 'CGCLOUD_NAMESPACE', defaults.namespace ),
                     help='Optional prefix for naming EC2 resource like instances, images, volumes, '
                          'etc. Use this option to create a separate namespace in order to avoid '
                          'collisions, e.g. when running tests. The default represents the root '
                          'namespace. The value of the environment variable CGCLOUD_NAMESPACE, if '
                          'that variable is present, overrides the default.' )

    def run(self, options):
        env = Environment( availability_zone=options.availability_zone,
                           namespace=options.namespace )
        return self.run_in_env( options, env )


class ListRolesCommand( Command ):
    """
    List available roles.
    """

    def run(self, options):
        print '\n'.join( BOXES.iterkeys( ) )


class RoleCommand( EnvironmentCommand ):
    """
    An abstract command that targets boxes of a particular role.  Note that there may be more
    than one instance per role. To target one of those instances, InstanceCommand might be a
    better choice.
    """

    def run_on_box(self, options, box):
        """
        Execute this command using the specified parsed command line options on the specified box.

        :param options: the parsed command line options
        :type options: dict
        :param box: the box to operate on
        :type box: Box
        """
        raise NotImplementedError( )

    def __init__(self, application, **kwargs):
        super( RoleCommand, self ).__init__( application, **kwargs )
        self.option( 'role',
                     metavar='ROLE',
                     help="The role name of the box to perform this command on. "
                          "Use the list command to show valid roles." )

    def run_in_env(self, options, env):
        role = options.role
        box_cls = BOXES.get( role )
        if box_cls is None: raise RuntimeError( "No such role: '%s'" % role )
        box = box_cls( env )
        return self.run_on_box( options, box )


class InstanceCommand( RoleCommand ):
    def __init__(self, application, **kwargs):
        super( InstanceCommand, self ).__init__( application, **kwargs )
        self.option( '--ordinal', '-o', default=None, type=int,
                     help='Selects an individual box among the boxes performing the same role. '
                          'The ordinal is an zero-based index into the list of all boxes performing '
                          'the given role, sorted by creation time. This means that the ordinal of '
                          'a box is not fixed, it may change if another box performing the same '
                          'role is terminated. This option is only required if there are multiple '
                          'boxes performing the same role.' )


class CreateCommand( RoleCommand ):
    """
    Create an EC2 instance of the specified box, install OS and additional packages on it,
    optionally create an AMI image of it, and/or terminate it.
    """

    def __init__(self, application):
        super( CreateCommand, self ).__init__( application )
        default_ec2_keypair_names = os.environ.get( 'CGCLOUD_KEYPAIRS', '' ).split( )
        self.option( '--keypairs', '-k', metavar='EC2_KEYPAIR_NAME',
                     dest='ec2_keypair_names', nargs='+',
                     required=not default_ec2_keypair_names,
                     default=default_ec2_keypair_names,
                     help='The names of EC2 keypairs whose public key is to be to injected into '
                          'the instance to facilitate SSH logins. For the first listed keypair a '
                          'matching private key needs to be present locally. The value of the '
                          'environment variable CGCLOUD_KEYPAIRS, if that variable is present, '
                          'overrides the default.' )

        self.option( '--instance-type', '-t', metavar='TYPE',
                     default=os.environ.get( 'CGCLOUD_INSTANCE_TYPE', None ),
                     help='The type of EC2 instance to launch for the box, e.g. t1.micro, m1.small, '
                          'm1.medium, or m1.large etc. The value of the environment variable '
                          'CGCLOUD_INSTANCE_TYPE, if that variable is present, overrides the '
                          'default, an instance type appropriate for the role.' )

        self.option( '--image', '-I',
                     default=False, action='store_true',
                     help='Create an image of the box when setup is complete.' )

        self.option( '--update', '-U',
                     default=False, action='store_true',
                     help="Bring the package repository as well as any installed packages up to "
                          "date, i.e. do what on Ubuntu is achieved by doing "
                          "'sudo apt-get update ; sudo apt-get upgrade'." )

        self.begin_mutex( )

        self.option( '--terminate', '-T',
                     default=None, action='store_true',
                     help='Terminate the box when setup is complete. The default is to leave the '
                          'box running except when errors occur.' )

        self.option( '--never-terminate', '-N',
                     default=None, dest='terminate', action='store_false',
                     help='Never terminate the box, even after errors. This may be useful for '
                          'post-mortem analysis.' )

        self.end_mutex( )

    def run_on_box(self, options, box):
        try:
            box.create( ec2_keypair_names=options.ec2_keypair_names,
                        instance_type=options.instance_type )
            box.setup( options.update )
            if options.image:
                box.stop( )
                box.create_image( )
                if options.terminate is not True:
                    box.start( )
        except:
            if options.terminate is not False:
                box.terminate( wait=False )
            raise
        else:
            if options.terminate is True:
                box.terminate( )


class CreateImageCommand( InstanceCommand ):
    """
    Create an AMI image of the instance. The instance must be stopped.
    """

    def run_on_box(self, options, box):
        box.adopt( ordinal=options.ordinal, wait_ready=False )
        box.create_image( )


class GetKeysCommand( InstanceCommand ):
    """
    Get a copy of the public keys that identify users on the instance.
    """

    def run_on_box(self, options, box):
        box.adopt( ordinal=options.ordinal )
        box.get_keys( )


class SshCommand( InstanceCommand ):
    """
    Start an interactive SSH session with the host.
    """

    def __init__(self, application):
        super( SshCommand, self ).__init__( application )
        self.option( '--user', '--login', '-u', '-l', default=None,
                     help="Name of user to login as." )

    def run_on_box(self, options, box):
        box.adopt( ordinal=options.ordinal )
        box.ssh( user=options.user )


class LifecycleCommand( InstanceCommand ):
    """
    Transition an instance into a particular state.
    """

    def adopt(self, box, options):
        box.adopt( ordinal=options.ordinal, wait_ready=False )

    def run_on_box(self, options, box):
        self.adopt( box, options )
        getattr( box, self.name( ) )( )


class StartCommand( LifecycleCommand ):
    """ Start the instance, ie. turn it on. """
    pass


class StopCommand( LifecycleCommand ):
    """ Stop the instance, ie. turn it off. """
    pass


class RebootCommand( LifecycleCommand ):
    """ Reboot the instance. """
    pass


class TerminateCommand( LifecycleCommand ):
    """ Terminate the instance, ie. delete it. """

    def __init__(self, application, **kwargs):
        super( TerminateCommand, self ).__init__( application, **kwargs )
        self.option( '--quick', '-q', default=False, action='store_true',
                     help="Exit immediately after termination request has been made, don't wait "
                          "until instance is actually terminated." )

    def run_on_box(self, options, box):
        self.adopt( box, options )
        box.terminate( wait=not options.quick )


class ShowCommand( InstanceCommand ):
    """
    Display the attributes of the EC2 instance.
    """

    def print_object(self, o, visited=set( ), depth=1):
        _id = id( o )
        if not _id in visited:
            visited.add( _id )
            self.print_dict( o.__dict__, visited, depth )
            visited.remove( _id )
        if depth == 1: sys.stdout.write( '\n' )

    def print_dict(self, d, visited, depth):
        for k, v in sorted( d.iteritems( ), key=itemgetter( 0 ) ):
            k = str( k )
            if k[ 0:1 ] != '_' \
                and k != 'connection' \
                and not isinstance( v, boto.ec2.connection.EC2Connection ):
                sys.stdout.write( '\n%s%s: ' % ('\t' * depth, k) )
                if isinstance( v, basestring ):
                    sys.stdout.write( v.strip( ) )
                elif hasattr( v, 'iteritems' ):
                    self.print_dict( v, visited, depth + 1 )
                elif hasattr( v, '__iter__' ):
                    self.print_dict( dict( enumerate( v ) ), visited, depth + 1 )
                elif isinstance( v, boto.ec2.blockdevicemapping.BlockDeviceType ) \
                    or isinstance( v, boto.ec2.group.Group ):
                    self.print_object( v, visited, depth + 1 )
                else:
                    sys.stdout.write( repr( v ) )

    def run_on_box(self, options, box):
        box.adopt( ordinal=options.ordinal, wait_ready=False )
        self.print_object( box.get_instance( ) )


class ListCommand( RoleCommand ):
    """
    List the instances performing a particular role
    """

    def run_on_box(self, options, box):
        for instance in box.list( ):
            print( '{role}\t{ordinal}\t{ip}\t{id}\t{created_at}\t{state}'.format( **instance ) )


class ListImages( RoleCommand ):
    """
    List the AMI images that were create from instances performing a particular role
    """

    def run_on_box(self, options, box):
        for image in box.list_images( ):
            print('{name}\t{ordinal}\t{id}\t{state}'.format( **image ))


class UploadKeyCommand( EnvironmentCommand ):
    """
    Import an OpenSSH public key for future injection into boxes
    """

    def __init__(self, application, **kwargs):
        super( UploadKeyCommand, self ).__init__( application, **kwargs )
        self.option( '--force', '-F', default=False, action='store_true',
                     help='Overwrite potentially existing EC2 key pair' )
        self.option( '--keypair', '-k', required=True, dest='ec2_keypair_name',
                     help='The desired name of the EC2 key pair.' )
        self.option( '--ssh-public-key', '-f', required=True,
                     help='A file containing the SSH public key to upload to the EC2 keypair.' )

    def run_in_env(self, options, env):
        with open( options.ssh_public_key ) as file:
            ssh_public_key = file.read( )
        env.upload_ssh_pubkey( ec2_keypair_name=options.ec2_keypair_name,
                               ssh_pubkey=ssh_public_key,
                               force=options.force )
