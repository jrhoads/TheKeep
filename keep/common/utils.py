import hashlib

from django.contrib.sites.models import Site

def absolutize_url(local_url):
    '''Convert a local url to an absolute url, with scheme and server name,
    based on the current configured :class:`~django.contrib.sites.models.Site`.
    
    :param local_url: local url to be absolutized, e.g. something generated by
        :meth:`~django.core.urlresolvers.reverse`
    '''
    if local_url.startswith('http'):
        return local_url

    # add scheme and server (i.e., the http://example.com) based
    # on the django Sites infrastructure.
    root = Site.objects.get_current().domain
    # but also add the http:// if necessary, since most sites docs
    # suggest using just the domain name
    if not root.startswith('http'):
        root = 'http://' + root
    return root + local_url

def md5sum(filename):
    '''Calculate and returns an MD5 checksum for the specified file.  Any file
    errors (non-existent file, read error, etc.) are not handled here but should
    be caught where this method is called.

    :param filename: ful path to the file for which a checksum should be calculated
    :returns: hex-digest formatted MD5 checksum as a string
    '''
    # pythonic md5 calculation from Stack Overflow
    # http://stackoverflow.com/questions/1131220/get-md5-hash-of-a-files-without-open-it-in-python
    md5 = hashlib.md5()
    with open(filename,'rb') as f:
        for chunk in iter(lambda: f.read(128*md5.block_size), ''):
             md5.update(chunk)
    return md5.hexdigest()





class PaginatedSolrSearch(object):
    # wrapper around sunburnt solrsearch so it can be passed to a django paginator
    # should be a temporary solution - looking into adding this to sunburnt 

    
    _result_cache = None
    def __init__(self, solrquery):
        self.solrquery = solrquery
        
    def count(self):
        print "** count "
        # get total count without retrieving any results
        # FIXME: cache the count?
        response = self.solrquery.paginate(rows=0).execute()
        return response.result.numFound

    def __len__(self):
        print "** len"
        if self._result_cache is None:
            self._result_cache = self.solrquery.execute()
        return len(self._result_cache)
                
            
    def __getitem__(self, k):
        """Return a single result or slice of results from the query."""
        
        print "** get item ", k
        if not isinstance(k, (slice, int, long)):
            raise TypeError
        
        if isinstance(k, slice):
            paginate_opts = {}
            # if start was specified, use it; otherwise retain current start
            if k.start is not None:
                paginate_opts['start'] = int(k.start)
            # if a slice bigger than available results is requested, cap it at actual max
            # FIXME: probably not actually necessary for solr...
            stop = min(k.stop, self.count())
            print "*paginate opts are "
                
            return PaginatedSolrSearch(self.solrquery.paginate(**paginate_opts))

        # check that index is in range
        # for now, not handling any fancy python indexing
        if k < 0 or k >= self.count():
            raise IndexError

        # index should be relative to currently paginated set
        if self._result_cache is None:
            self._result_cache = self.solrquery.execute()
            
        return self._result_cache[k]

