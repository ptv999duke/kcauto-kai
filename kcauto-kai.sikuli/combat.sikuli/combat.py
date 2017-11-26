from sikuli import Region, Pattern, FOREVER
from datetime import datetime, timedelta
from threading import Thread
from globals import Globals
from fleet import Fleet
from lbas import LBAS
from mapData import MapData
from nav import Nav
from util import Util


class CombatModule(object):
    def __init__(self, config, stats, regions, fleets):
        """Initializes the Combat module.

        Args:
            config (Config): kcauto-kai Config instance
            stats (Stats): kcauto-kai Stats instance
            regions (dict): dict of pre-defined kcauto-kai regions
            fleets (dict): dict of active CombatFleet instances
        """
        self.config = config
        self.stats = stats
        self.regions = regions
        self.kc_region = regions['game']
        self.fleets = fleets
        self.primary_fleet = (
            fleets[3]
            if self.config.combat['fleet_mode'] == 'striking' else fleets[1])

        self.next_combat_time = datetime.now()
        self.dmg = {}
        self.map = MapData(
            self.config.combat['map'], self.regions, self.config)
        self.current_position = [0, 0]
        self.current_node = None

        self.combined_fleet = (
            True if self.config.combat['combined_fleet'] else False)
        self.fleet_icon = 'fleet_icon_standard.png'
        if self.config.combat['combined_fleet']:
            self.fleet_icon = 'fleet_icon_{}.png'.format(
                self.config.combat['fleet_mode'])

        self.lbas = (
            LBAS(config, regions, self.map)
            if self.config.combat['lbas_enabled'] else None)

    def goto_combat(self):
        """Method to navigate to the combat menu.
        """
        Nav.goto(self.regions, 'combat')

    def check_need_to_sortie(self):
        """Method to check whether the combat fleets need to sortie based on
        the stored next combat time.

        Returns:
            bool: True if the combat fleets need to sortie, False otherwise
        """
        if self.next_combat_time < datetime.now():
            return True
        return False

    def _set_next_combat_time(self, delta={}):
        """Method to set the next combat time based on the provided hours,
        minutes, and seconds delta.

        Args:
            delta (dict, optional): dict containing the hours, minutes, and
                seconds delta
        """
        self.next_combat_time = datetime.now() + timedelta(
            hours=delta['hours'] if 'hours' in delta else 0,
            minutes=delta['minutes'] if 'minutes' in delta else 0,
            seconds=delta['seconds'] if 'seconds' in delta else 0)

    def combat_logic_wrapper(self):
        """Method that fires off the necessary child methods that encapsulates
        the entire action of sortieing combat fleets and resolving combat.

        Returns:
            bool: False if the combat fleets could not be sortied
        """
        self.stats.increment_combat_attempted()

        if not self._select_combat_map():
            # LBAS fatigue check failed; cancel sortie
            return False

        if self._conduct_pre_sortie_checks():
            start_button = 'combat_start.png'
            if self.lbas:
                start_button = 'combat_start_lbas.png'
            if not Util.check_and_click(
                    self.regions['lower_right'], start_button):
                # generic sortie fail catch
                Util.log_warning("Could not begin sortie for some reason!")
                self._set_next_combat_time()
                return False
        else:
            # fleet fatigue/damage check failed; cancel sortie
            return False

        if self.config.combat['combined_fleet']:
            self.fleets[1].reset_fcf_retreat_counts()
            self.fleets[2].reset_fcf_retreat_counts()

        # background observer for tracking the fleet position
        observeRegion = Region(self.kc_region)
        observeRegion.onAppear(
            Pattern(self.fleet_icon).similar(Globals.FLEET_ICON_SIMILARITY),
            self._update_fleet_position)
        observeRegion.observeInBackground(FOREVER)

        self._run_combat_logic()

        if self.config.combat['combined_fleet']:
            self.fleets[1].resolve_fcf_retreat_counts()
            self.fleets[2].resolve_fcf_retreat_counts()

        # stop the background observer once combat is complete
        observeRegion.stopObserver()
        return True

    def _select_combat_map(self):
        """Method that goes through the menu and chooses the specified map to
        sortie to. LBAS checks are also resolved at this point.

        Returns:
            bool: True if the combat map is successfully chosen and started,
                False if an LBAS check failed
        """
        Util.rejigger_mouse(self.regions, 'top')

        if self.map.world == 'event':
            Util.wait_and_click(
                self.regions['lower'],
                '_event_world.png')
        else:
            Util.wait_and_click_and_wait(
                self.regions['lower'],
                'c_world_{}.png'.format(self.map.world),
                self.kc_region,
                'c_world_{}-1.png'.format(self.map.world))
        Util.rejigger_mouse(self.regions, 'top')

        if self.lbas:
            # resupply and delay sortie time if LBAS fails fatigue check
            lbas_check_fatigue = (
                'CheckFatigue' in self.config.combat['misc_options'])
            pass_lbas_check, delay_time = (
                self.lbas.resupply_groups(lbas_check_fatigue))
            if not pass_lbas_check:
                self._set_next_combat_time({'minutes': delay_time})
                return False

        if self.map.world == 'event':
            for page in range(1, int(self.map.subworld[0])):
                Util.check_and_click(
                    self.kc_region, '_event_next_page_{}.png'.format(page))
                Util.rejigger_mouse(self.regions, 'top')
                Util.kc_sleep(2)
            Util.wait_and_click(
                self.kc_region,
                '_event_world_{}.png'.format(self.map.subworld))
            # dismiss Ooyodo chalkboards
            self.kc_region.wait('event_chalkboard.png', 10)
            while self.kc_region.exists('event_chalkboard'):
                Util.kc_sleep(1)
                Util.click_screen(self.regions, 'center')
                Util.kc_sleep(1)
                if self.regions['lower_right'].exists('sortie_select.png'):
                    break
        else:
            if int(self.map.subworld) > 4:
                Util.wait_and_click(
                    self.regions['right'], 'c_world_eo_arrow.png')
                Util.rejigger_mouse(self.regions, 'top')
                Util.kc_sleep(2)
            Util.wait_and_click(self.kc_region, 'c_world_{}-{}.png'.format(
                self.map.world, self.map.subworld))
        Util.wait_and_click(self.regions['lower_right'], 'sortie_select.png')
        Util.rejigger_mouse(self.regions, 'top')
        return True

    def _conduct_pre_sortie_checks(self):
        """Method to conduct pre-sortie fatigue and supply checks on the
        combat fleets as needed.

        Returns:
            bool: True if the fleet passes the pre-sortie checks, False
                otherwise
        """
        cancel_sortie = False

        if self.config.combat['fleet_mode'] == 'striking':
            # switch fleet to 3rd fleet if striking fleet
            Util.kc_sleep(1)
            self._switch_fleet_pre_sortie(3)

        needs_resupply, self.dmg, fleet_fatigue = (
            self._run_pre_sortie_fleet_check_logic(self.primary_fleet))

        if self.combined_fleet:
            # additional combined fleet checks
            self._switch_fleet_pre_sortie(2)
            two_needs_resupply, fleet_two_damages, fleet_two_fatigue = (
                self._run_pre_sortie_fleet_check_logic(self.fleets[2]))
            self._switch_fleet_pre_sortie(1)

            self.dmg = self._combine_fleet_damages(self.dmg, fleet_two_damages)
            for key in fleet_fatigue:
                fleet_fatigue[key] = (
                    fleet_fatigue[key] or fleet_two_fatigue[key])

        if needs_resupply:
            Util.log_warning("Canceling combat sortie: resupply required.")
            self._set_next_combat_time()
            cancel_sortie = True

        if 'CheckFatigue' in self.config.combat['misc_options']:
            if fleet_fatigue['high']:
                Util.log_warning(
                    "Canceling combat sortie: fleet has high fatigue.")
                self._set_next_combat_time({'minutes': 25})
                cancel_sortie = True
            elif fleet_fatigue['medium']:
                Util.log_warning(
                    "Canceling combat sortie: fleet has medium fatigue.")
                self._set_next_combat_time({'minutes': 15})
                cancel_sortie = True

        # just use fleet 1's method
        damage_counts_at_threshold = (
            self.primary_fleet.get_damage_counts_at_threshold(
                self.config.combat['repair_limit'], self.dmg))

        if damage_counts_at_threshold > 0:
            Util.log_warning(
                "Canceling combat sortie: {:d} ships above damage threshold."
                .format(damage_counts_at_threshold))
            self._set_next_combat_time()
            cancel_sortie = True

        if ('PortCheck' in self.config.combat['misc_options'] or
                self.map.world == 'event'):
            port_full_notice = (
                'warning_port_full_event.png'
                if self.map.world == 'event' else 'warning_port_full.png')
            if self.regions['lower'].exists(port_full_notice):
                Util.log_warning("Canceling combat sortie: port is full.")
                self._set_next_combat_time({'minutes': 15})
                cancel_sortie = True

        if cancel_sortie:
            return False
        return True

    def _run_pre_sortie_fleet_check_logic(self, fleet):
        """Method that actually does the checking of supplies and damages of
        the fleet during the pre-sortie fleet check. Also includes special
        handling of the 7th ship in striking fleets.

        Args:
            fleet (CombatFleet): CombatFleet instance of fleet being checked

        Returns:
            bool: indicates whether or not the fleed requires resupply
            dict: dict of combat damages
            dict: dict of fleet fatigue
        """
        needs_resupply = False
        if not fleet.check_supplies(self.regions['check_supply']):
            fleet.needs_resupply = True
            needs_resupply = True
        fleet_damages = (
            fleet.check_damages_7th(self.regions)
            if self.config.combat['fleet_mode'] == 'striking'
            else fleet.check_damages(self.regions['check_damage']))

        if 'CheckFatigue' in self.config.combat['misc_options']:
            fleet_fatigue = fleet.check_fatigue(
                self.regions['check_fatigue'])
            return (needs_resupply, fleet_damages, fleet_fatigue)
        return (needs_resupply, fleet_damages, {})

    def _run_combat_logic(self):
        """Method that contains the logic and fires off necessary child methods
        for resolving anything combat-related. Includes LBAS node assignment,
        compass spins, formation selects, night battle selects, FCF retreats
        for combined fleet, flagship retreats, mid-battle damage checks, and
        resource node ends.
        """
        self.stats.increment_combat_done()

        if self.lbas:
            self.lbas.assign_groups()

        self.primary_fleet.needs_resupply = True
        if self.combined_fleet:
            self.fleets[2].needs_resupply = True

        # primary combat loop
        sortieing = True
        nodes_run = []
        while sortieing:
            at_node = self._run_loop_between_nodes()

            if at_node:
                # arrived at combat node
                nodes_run.append(self.current_node)

                # get rid of initial boss dialogue
                Util.kc_sleep(5)
                Util.click_screen(self.regions, 'center')
                Util.kc_sleep()
                Util.click_screen(self.regions, 'center')
                Util.rejigger_mouse(self.regions, 'lbas')

                combat_result = self._run_loop_during_battle()

                # resolve night battle
                if combat_result == 'night_battle':
                    if self.map.resolve_night_battle(nodes_run[-1]):
                        self._run_loop_during_battle()

                self.regions['lower_right_corner'].wait('next.png', 30)

                # battle complete; resolve combat results
                Util.click_screen(self.regions, 'center')
                self.regions['game'].wait('mvp_marker.png', 30)
                self.dmg = self.primary_fleet.check_damages(
                    self.regions['check_damage_combat'])
                if self.combined_fleet:
                    self.regions['lower_right_corner'].wait('next.png', 30)
                    Util.click_screen(self.regions, 'center')
                    Util.kc_sleep(2)
                    self.regions['game'].wait('mvp_marker.png', 30)
                    fleet_two_damages = self.fleets[2].check_damages(
                        self.regions['check_damage_combat'])
                    self.dmg = self._combine_fleet_damages(
                        self.dmg, fleet_two_damages)
                Util.rejigger_mouse(self.regions, 'lbas')
                # click through while not next battle or home
                while not (
                        self.kc_region.exists('home_menu_sortie.png') or
                        self.kc_region.exists('combat_flagship_dmg.png') or
                        self.kc_region.exists('combat_retreat.png')):
                    if self.regions['lower_right_corner'].exists('next.png'):
                        Util.click_screen(self.regions, 'center')
                        Util.rejigger_mouse(self.regions, 'lbas')
                    elif self.regions['lower_right_corner'].exists(
                            'next_alt.png'):
                        Util.click_screen(self.regions, 'center')
                        Util.rejigger_mouse(self.regions, 'lbas')
                    elif self.combined_fleet:
                        self._fcf_resolver()

            if self.regions['left'].exists('home_menu_sortie.png'):
                # arrived at home; sortie complete
                self._print_sortie_complete_msg(nodes_run)
                sortieing = False
                break

            if self.regions['lower_right_corner'].exists(
                    'combat_flagship_dmg.png'):
                # flagship retreat; sortie complete
                Util.log_msg("Flagship damaged. Automatic retreat.")
                Util.click_screen(self.regions, 'game')
                self.regions['left'].wait('home_menu_sortie.png', 30)
                self._print_sortie_complete_msg(nodes_run)
                sortieing = False
                break

            if self.kc_region.exists('combat_retreat.png'):
                retreat = False
                # check whether to retreat against combat nodes count
                if len(nodes_run) >= self.config.combat['combat_nodes']:
                    Util.log_msg(
                        "Ran the necessary number of nodes. Retreating.")
                    retreat = True

                # check whether to retreat against fleet damage state
                threshold_dmg_count = (
                    self.primary_fleet.get_damage_counts_at_threshold(
                        self.config.combat['retreat_limit'],
                        self.dmg))
                if threshold_dmg_count > 0:
                    Util.log_warning(
                        "{} ship(s) damaged above threshold. Retreating."
                        .format(threshold_dmg_count))
                    retreat = True

                # resolve retreat/continue
                if retreat:
                    self.map.select_sortie_continue_retreat(True)
                    self.regions['left'].wait('home_menu_sortie.png', 30)
                    self._print_sortie_complete_msg(nodes_run)
                    sortieing = False
                    break
                else:
                    self.map.select_sortie_continue_retreat(False)

    def _print_sortie_complete_msg(self, nodes_run):
        """Method that prints the post-sortie status report indicating number
        of nodes run and nodes run.

        Args:
            nodes_run (list): list of Nodes run in the primary combat logic
        """
        Util.log_success(
            "Sortie complete. Encountered {} combat nodes (nodes {}).".format(
                len(nodes_run), ', '.join(str(node) for node in nodes_run)))

    def _run_loop_between_nodes(self):
        """Method that continuously checks for the next update between combat
        nodes. Resolves compass spins, formation selects, node selects, and
        resource node ends.

        Returns:
            bool: True if the method ends on a combat node, False otherwise
        """
        at_node = False
        formation_check = (
            'formation_combinedfleet_1'
            if self.config.combat['combined_fleet']
            else 'formation_line_ahead')

        while not at_node:
            if self.kc_region.exists('compass.png'):
                while (self.kc_region.exists('compass.png')):
                    Util.click_screen(self.regions, 'center')
                    Util.kc_sleep(3)
            elif self.regions[formation_check].exists(
                    '{}.png'.format(formation_check)):
                Util.log_msg("Fleet at Node {}".format(self.current_node))
                self.map.resolve_formation(self.current_node)
                Util.rejigger_mouse(self.regions, 'top')
                at_node = True
                return True
            elif self.kc_region.exists('combat_node_select.png'):
                if (
                        self.current_node.name
                        in self.config.combat['node_selects']):
                    next_node = self.config.combat['node_selects'][
                        self.current_node.name]
                    self.map.nodes[next_node].click_node(self.regions['game'])
                    Util.rejigger_mouse(self.regions, 'lbas')
            elif self.regions['lower_right_corner'].exists(
                    'combat_flagship_dmg.png'):
                return False
            elif (self.regions['lower_right_corner'].exists('next_alt.png') or
                    self.regions['lower_right_corner'].exists('next.png') or
                    self.kc_region.exists('combat_nb_fight.png')):
                at_node = True
                return True

    def _run_loop_during_battle(self):
        """Method that continuously runs during combat for the night battle
        prompt or battle end screen.

        Returns:
            str: 'night_battle' if combat ends on the night battle prompt,
                'results' if otherwise
        """
        while True:
            if self.kc_region.exists('combat_nb_fight.png'):
                return 'night_battle'
            elif (self.kc_region.exists('next.png')
                    or self.kc_region.exists('next_alt.png')):
                return 'results'
            else:
                pass

    def _switch_fleet_pre_sortie(self, fleet):
        """Method that switches the fleet in the pre-sortie fleet selection
        screen to the specified fleet.

        Args:
            fleet (int): id of fleet to switch to
        """
        Util.wait_and_click_and_wait(
            self.regions['top_submenu'],
            Pattern('fleet_{}.png'.format(fleet)).exact(),
            self.regions['top_submenu'],
            Pattern('fleet_{}_active.png'.format(fleet)).exact())

    def _update_fleet_position(self, event):
        """Method that is run by the fleet observer to continuously update the
        fleet's status.

        Args:
            event (event): sikuli observer event
        """
        lastMatch = event.getMatch()
        # lastMatch is based off of screen positions, so subtract game region
        # x and y to get in-game positions
        self.current_position = [
            lastMatch.x + (lastMatch.w / 2) - self.kc_region.x,
            lastMatch.y + lastMatch.h - self.kc_region.y
        ]

        # debug console print for the observer's found position of the fleet
        """
        print(
            "{}, {} ({})".format(
                self.current_position[0], self.current_position[1], lastMatch))
        """
        matched_node = self.map.find_node_by_pos(*self.current_position)
        self.current_node = (
            matched_node if matched_node is not None else self.current_node)
        event.repeat()

    def _fcf_resolver(self):
        """Method that resolves the FCF prompt. Does not use FCF if there are
        more than one ship in a heavily damaged state.
        """
        if self.regions['lower_left'].exists('fcf_retreat_ship.png'):
            fleet_1_heavy_damage = self.fleets[1].damage_counts['heavy']
            fleet_2_heavy_damage = self.fleets[2].damage_counts['heavy']
            if fleet_1_heavy_damage + fleet_2_heavy_damage is 1:
                self.fleets[1].increment_fcf_retreat_count()
                self.fleets[2].increment_fcf_retreat_count()
                if (Util.check_and_click(
                        self.regions['lower'], 'fcf_retreat_ship.png')):
                    self.dmg['heavy'] -= 1
            else:
                Util.log_warning("Declining to retreat ship with FCF.")
                Util.check_and_click(
                    self.regions['lower'], 'fcf_continue_fleet.png')

    def _combine_fleet_damages(self, main, escort):
        """Method for conveniently combining two damage dicts for combined
        fleets.

        Args:
            main (dict): damage dict of main fleet
            escort (dict): damage dict of escort fleet

        Returns:
            dict: damage dict aggregating all damage counts for both main and
                escort fleets
        """
        combined = {}  # create new to not update by reference
        for key in main:
            combined[key] = main[key] + escort[key]
        return combined

    def print_status(self):
        """Method that prints the next sortie time status of the Combat module.
        """
        Util.log_success("Next combat sortie at {}".format(
            self.next_combat_time.strftime('%Y-%m-%d %H:%M:%S')))


class CombatFleet(Fleet):
    def __init__(self, fleet_id):
        """Initializes the CombatFleet object, an extension of the Fleet class.

        Args:
            fleet_id (int): id of the fleet
        """
        self.fleet_id = fleet_id
        self.damage_counts = {}
        self.damaged_fcf_retreat_count = 0
        self.fatigue = {}

    def reset_fcf_retreat_counts(self):
        """Method for setting the fleet's damaged FCF retreat counter.
        """
        self.damaged_fcf_retreat_count = 0

    def resolve_fcf_retreat_counts(self):
        """Method for resolving the fleet's damaged FCF retreat counter by
        adding it back to the damage counter at the end of a sortie.
        """
        self.damage_counts['heavy'] += self.damaged_fcf_retreat_count
        self.reset_fcf_retreat_counts()

    def increment_fcf_retreat_count(self):
        """Method to increment the FCF retreat count if there is only one
        heavily damaged ship in the fleet, and decrement the heavy damage from
        the damage counter.
        """
        if 'heavy' in self.damage_counts and self.damage_counts['heavy'] is 1:
            Util.log_msg(
                "Retreating damaged ship via FCF from fleet {}."
                .format(self.fleet_id))
            self.damaged_fcf_retreat_count += 1
            self.damage_counts['heavy'] -= 1

    def get_damage_counts_at_threshold(self, threshold, counts={}):
        """Method for returning the number of ships at and below the specified
        damage threshold

        Args:
            threshold (str): the cutoff damage threshold
            counts (dict, optional): optionally passed in damage counts; if not
                specified, the fleet's internally stored damage counter is used
                to calculate the number

        Returns:
            int: the number of ships at or below the damage threshold
        """
        if not counts:
            counts = self.damage_counts

        valid_damages = self.get_damages_at_threshold(threshold)

        count = 0
        for damage in valid_damages:
            count += counts[damage]

        return count

    def check_damages(self, region, reset=True):
        """Method to multithread the detection of damage states of the fleet.

        Args:
            region (Region): Region in which to search for the damage states

        Returns:
            dict: dict of counts of the different damage states
        """
        thread_check_damages_heavy = Thread(
            target=self._check_damages_func, args=('heavy', region, reset))
        thread_check_damages_moderate = Thread(
            target=self._check_damages_func, args=('moderate', region, reset))
        thread_check_damages_minor = Thread(
            target=self._check_damages_func, args=('minor', region, reset))
        Util.multithreader([
            thread_check_damages_heavy, thread_check_damages_moderate,
            thread_check_damages_minor])
        return self.damage_counts

    def _check_damages_func(self, type, region, reset):
        """Child multithreaded method for checking damage states.

        Args:
            type (str): which damage state to check for
            region (Region): Region in which to search for the damage state
        """
        if reset:
            self.damage_counts[type] = 0

        dmg_img = 'ship_state_dmg_{}.png'.format(type)
        count = Util.findAll_wrapper(
            region, Pattern(dmg_img).similar(Globals.DAMAGE_SIMILARITY))

        for i in count:
            self.damage_counts[type] += 1

    def check_damages_7th(self, regions):
        """Method that specifically checks the damage in the 7th ship spot
        of the fleet during the pre-sortie damage check.

        Args:
            regions (dict): dict of pre-defined kcauto-kai regions

        Returns:
            dict: dict of counts of the different damage states, including that
                of the 7th ship
        """
        self.check_damages(regions['check_damage'])
        Util.click_screen(regions, '7th_next')
        return self.check_damages(regions['check_damage_7th'], reset=False)

    def check_fatigue(self, region):
        """Method to multithread the detection of fatigue states of the fleet.

        Args:
            region (Region): Region in which to search for the fatigue states

        Returns:
            dict: dict of bools of the different fatigue states
        """
        thread_check_low_fatigue = Thread(
            target=self._check_fatigue_func, args=('medium', region))
        thread_check_high_fatigue = Thread(
            target=self._check_fatigue_func, args=('high', region))
        Util.multithreader([
            thread_check_low_fatigue, thread_check_high_fatigue])
        print(self.fatigue)
        return self.fatigue

    def _check_fatigue_func(self, mode, region):
        """Child multithreaded method for checking fatigue states.

        Args:
            type (str): which fatigue state to check for
            region (Region): Region in which to search for the fatigue state
        """
        self.fatigue[mode] = (
            True
            if (region.exists(Pattern('ship_state_fatigue_{}.png'.format(mode))
                .similar(Globals.FATIGUE_SIMILARITY)))
            else False)

    @staticmethod
    def get_damages_at_threshold(threshold):
        """Method for returning the list of valid damages given a threshold.

        Args:
            threshold (str): the cutoff damage threshold

        Returns:
            list: list of valid damages (heavy, moderate, minor)
        """
        valid_damages = ('heavy', 'moderate', 'minor')
        return valid_damages[:valid_damages.index(threshold) + 1]