This directory exists so that Subversion-based projects can share a single
copy of the ``ez_setup`` bootstrap module for ``setuptools``, and have it
automatically updated in their projects when ``setuptools`` is updated.

For your convenience, you may use the following svn:externals definition::

    ez_setup svn://svn.eby-sarna.com/svnroot/ez_setup

You can set this by executing this command in your project directory::

    svn propedit svn:externals .

And then adding the line shown above to the file that comes up for editing.
Then, whenever you update your project, ``ez_setup`` will be updated as well.

