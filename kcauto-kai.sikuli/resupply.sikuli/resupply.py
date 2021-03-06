from fleet import Fleet
from nav import Nav
from util import Util


class ResupplyModule(object):
    def __init__(self, config, stats, regions, fleets):
        """Initializes the Resupply module.

        Args:
            config (Config): kcauto-kai Config instance
            stats (Stats): kcauto-kai Stats instance
            regions (dict): dict of pre-defined kcauto-kai regions
            fleets (dict): dict of active Fleet instances
        """
        self.config = config
        self.stats = stats
        self.regions = regions
        self.fleets = fleets

    def goto_resupply(self):
        """Method to navigate to the resupply menu
        """
        Nav.goto(self.regions, 'resupply')

    def check_need_to_resupply(self):
        """Method that determines whether or not any of the active fleets need
        resupplies.

        Returns:
            boolean: True if an active fleet needs resupply, False otherwise
        """
        for fleet_id, fleet in self.fleets.items():
            if fleet.needs_resupply:
                return True
        return False

    def resupply_fleets(self):
        """Method that goes through the fleets and resupplies them in the
        resupply menu.
        """
        Util.log_msg("Begin resupplying fleets.")
        for fleet_id, fleet in self.fleets.items():
            if fleet.needs_resupply:
                Util.log_msg("Resupplying fleet {}.".format(fleet_id))
                if fleet_id != 1:
                    Fleet.switch(self.regions['top_submenu'], fleet.fleet_id)
                Util.wait_and_click_and_wait(
                    self.regions['top_submenu'], 'resupply_all.png',
                    self.regions['lower_right'], 'resupply_all_done.png')
                Util.kc_sleep()
                self.stats.increment_resupplies_done()
                fleet.needs_resupply = False
                Util.kc_sleep()
        Util.log_msg("Done resupplying fleets.")
