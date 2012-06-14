import sys
from collections import defaultdict
from r2.models import *

def fix_trans_id():
    bad_campaigns = list(PromoCampaign._query(PromoCampaign.c.trans_id == 1, data=True))
    num_bad_campaigns = len(bad_campaigns)

    if not num_bad_campaigns:
        print "No campaigns with trans_id == 1"
        return

    # print some info and prompt user to continue
    print ("Found %d campaigns with trans_id == 1. \n"
           "Campaigns ids: %s \n" 
           "Press 'c' to fix them or any other key to abort." %
           (num_bad_campaigns, [pc._id for pc in bad_campaigns]))
    input_char = sys.stdin.read(1)
    if input_char != 'c' and input_char != 'C':
        print "aborting..."
        return

    # log the ids for reference
    print ("Fixing %d campaigns with bad freebie trans_id: %s" % 
           (num_bad_campaigns, [pc._id for pc in bad_campaigns]))

    # get corresponding links and copy trans_id from link data to campaign thing
    link_ids = set([campaign.link_id for campaign in bad_campaigns])
    print "Fetching associated links: %s" % link_ids
    try:
        links = Link._byID(link_ids, data=True, return_dict=False)
    except NotFound, e:
        print("Invalid data: Some promocampaigns have invalid link_ids. "
              "Please delete these campaigns or fix the data before "
              "continuing. Exception: %s" % e)

    # organize bad campaigns by link_id
    bad_campaigns_by_link = defaultdict(list)
    for c in bad_campaigns:
        bad_campaigns_by_link[c.link_id].append(c)

    # iterate through links and copy trans_id from pickled list on the link to 
    # the campaign thing
    failed = []
    for link in links:
        link_campaigns = getattr(link, "campaigns")
        thing_campaigns = bad_campaigns_by_link[link._id]
        for campaign in thing_campaigns:
            try:
                sd, ed, bid, sr_name, trans_id = link_campaigns[campaign._id]
                if trans_id != campaign.trans_id:
                    campaign.trans_id = trans_id
                    campaign._commit()
            except:
                failed.append({
                    'link_id': link._id,
                    'campaign_id': campaign._id,
                    'exc type': sys.exc_info()[0],
                    'exc msg': sys.exc_info()[1]
                })

    # log the actions for future reference
    msg = ("%d of %d campaigns updated successfully. %d updates failed: %s" %
           (num_bad_campaigns, num_bad_campaigns - len(failed), len(failed), failed))
    print msg

        
