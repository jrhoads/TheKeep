class Content < ActiveRecord::Base
  has_many :AccessRights
  belongs_to :DescriptionData, :foreign_key => "collection_number"
  has_and_belongs_to_many :genres
  has_and_belongs_to_many :languages
  belongs_to :Location
  has_and_belongs_to_many :names
  belongs_to :ResourceType
  has_many :src_still_images
  belongs_to :StaffName, :foreign_key => "completed_by"
  has_and_belongs_to_many :subjects
  
  RECORD_ID_TYPES = [
    ["local", "local"], 
    ["Other - Record in Content Notes"]
  ].freeze  

  def self.findNext(id)  
    c = find(:all,
      :conditions => "id > #{id}",
      :order => 'id',
      :limit => '1')     
      return c[0]
  end

  def self.findPrevious(id)  
    c = find(:all,
      :conditions => "id < #{id}",
      :order => 'id DESC',
      :limit => '1')     
      return c[0]
  end



  def self.search(options)  
    conditions = "1=1 "
    joins = "AS c "
    vals = Array.new
   if (not(options[:mss_number].nil?) and options[:mss_number] != '')
     joins += "LEFT JOIN description_datas as dd on c.collection_number = dd.id "
     conditions += "and dd.mss_number = ? "
     vals.push(options[:mss_number])
   end  
   if (not(options[:id].nil?) and options[:id] != '')
     conditions += "and c.id = ?"
     vals.push(options[:id])
   end  
   if (not(options[:title].nil?) and options[:title] != '')
   ## keyword search instead of phrase
     words = options[:title].split
     for w in words
     # note : allow ruby/rails to do search term escaping (for characters like ')
        conditions += "and c.title ILIKE ? "     
        vals.push("%#{w}%")
     end
   end  
   if (options[:name] != nil and options[:name][:id] != '')
      joins += " LEFT JOIN contents_names as cn ON c.id = cn.content_id"
      conditions += "and cn.name_id = #{options[:name][:id]}"
      # role is only used in tandem with a name
      unless (options[:role][:id] == '')
        conditions += "and cn.role_id = #{options[:role][:id]}"  
      end 
   end
   if (options[:resource] != nil and options[:resource][:type] != '')
     conditions += "and c.resource_type_id = #{options[:resource][:type]}"
   end  
   if (options[:image_note] != '')
     joins += " LEFT JOIN tech_images AS ti ON c.id = ti.content_id "
     words = options[:image_note].split
     for w in words
        conditions += "and ti.image_note ILIKE ? "
        vals.push("%#{w}%") 
     end
   end  
   if ( options[:image] != nil and options[:image][:format] != '')
     joins += " LEFT JOIN src_still_images AS ssi ON c.id = ssi.content_id "
     conditions += " and ssi.form_id = #{options[:image][:format]}"
   end
 # filter by date: before, after, or both (between)
  if (options[:date_mode] != nil and options[:date_mode] != 'none')
    case options[:date_mode]
      when "Before"
       conditions += "and c.date_created < '#{options[:before][:year]}-#{options[:before][:month]}-#{options[:before][:day]}' "
      when "After"
        conditions += "and c.date_created > '#{options[:after][:year]}-#{options[:after][:month]}-#{options[:after][:day]}' "
      when "Between"
        conditions += "and c.date_created < '#{options[:before][:year]}-#{options[:before][:month]}-#{options[:before][:day]}' "
        conditions += "and c.date_created > '#{options[:after][:year]}-#{options[:after][:month]}-#{options[:after][:day]}' "
    end
  end
 
 # filter - records with no subjects (for canned searches)
   if (options[:filter] == "no_subject")
     joins += " LEFT JOIN contents_subjects as cs ON c.id = cs.content_id"
     conditions += " and cs.id is null";
   end

  # make conditions text first member of vals array   
   vals.unshift(conditions)
    
    find(:all,
#      :select     => 'c.id, c.record_id_type, c.other_id, c.date_created, c.date_modified, c.collection_number, c.title, c.subtitle, c.resource_type_id, c.location_id, c.abstract, c.toc, c.content_notes, c.completed_by, c.completed_date',
      :select     => 'c.*',
      :joins      => joins,
      :conditions => vals)
  end

end